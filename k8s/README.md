# Kubernetes Deployment Guide

This guide provides step-by-step instructions for deploying the data pipeline infrastructure on Kubernetes using Minikube.

## Prerequisites

- Minikube installed
- kubectl installed
- Docker installed

## Quick Start

### 1. Start Minikube and Setup Namespace

```bash
minikube start

# Create the 'batch' namespace
kubectl create namespace batch

# Set current namespace to 'batch'
kubectl config set-context --current --namespace=batch

# Verify namespace is set
kubectl config view --minify --output 'jsonpath={..namespace}'
```

### 2. Deploy Infrastructure Components

Deploy the components in the following order to ensure proper dependencies:

#### Step 1: Deploy Datalake
```bash
kubectl apply -f datalake.yaml
```
**Note**: Make sure you configure more storage space in the PersistentVolumeClaim before deployment. The default 50Mi is too small for PostgreSQL production use. Recommended:
- **Development/Testing**: Increase to at least 2-5Gi
- **Production**: Use 10Gi or more depending on data volume
- Edit `datalake.yaml` and change `storage: 50Mi` to `storage: 5Gi` before applying

**Warning**: Running out of storage space can cause PostgreSQL to crash and potentially lose data. Always provision adequate storage.
#### Step 2: Deploy Kafka Stack (in order)

**1. Deploy Zookeeper first:**
```bash
kubectl apply -f kafka/zookeeper.yaml
```

**2. Deploy Kafka Broker:**
```bash
kubectl apply -f kafka/kafka.yaml
```

**3. Deploy Schema Registry:**
```bash
kubectl apply -f kafka/schema-registry.yaml
```

**4. Deploy Kafka UI:**
```bash
kubectl apply -f kafka/kafka-ui.yaml
```

**5. Deploy Debezium Connect:**
```bash
kubectl apply -f debezium-connect.yaml
```

#### Step 3: Deploy Minio
```bash
kubectl apply -f minio.yaml
```
**Note**: Make sure you configure more storage space in the PersistentVolumeClaim before deployment.
### 3. Check Deployment Status
**Note**: Wait until all pods are running before proceeding
#### Check Pods Status
```bash
kubectl get pods -n batch
```

#### Check Services Status
```bash
kubectl get svc -n batch
```

#### Check Deployments Status
```bash
kubectl get deployment -n batch
```

#### Check PersistentVolumeClaims Status
```bash
kubectl get pvc -n batch
```

#### Check All Resources at Once
```bash
kubectl get all -n batch

kubectl get all,pvc -n batch
```

## Testing the Data Pipeline

This section guides you through testing the complete pipeline: PostgreSQL → Debezium → Kafka

### Step 1: Create Test Table in PostgreSQL

First, access the PostgreSQL pod and create a test table:

```bash
# Get the PostgreSQL pod name
kubectl get pods -n batch -l app=datalake

# Access PostgreSQL pod
kubectl exec -it -n batch <datalake-pod-name> -- psql -U admin -d busdb

# Or use port-forward method (open in new terminal)
kubectl port-forward -n batch service/datalake 5432:5432
# Then connect: psql -h localhost -p 5432 -U admin -d busdb
```

Inside PostgreSQL, create a test table:
```sql
-- Create a test table
CREATE TABLE test_users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Enable logical replication (required for Debezium)
ALTER TABLE test_users REPLICA IDENTITY FULL;

-- Insert initial test data
INSERT INTO test_users (name, email) VALUES 
    ('John Doe', 'john@example.com'),
    ('Jane Smith', 'jane@example.com');

-- Verify data
SELECT * FROM test_users;

-- Keep this session open for later data insertion
```

### Step 2: Port Forward Debezium Connect (New Terminal)

Open a new terminal and set up port forwarding for Debezium Connect:

```bash
# Port forward Debezium Connect
kubectl port-forward -n batch service/debezium-connect 8083:8083
```

Keep this terminal running.

### Step 3: Configure Debezium Connector with Postman

1. **Import Postman Collection:**
   - Open Postman
   - Click "Import"
   - Select the file: `k8s/Debezium.postman_collection.json`

2. **Create a PostgreSQL Connector:**
   - Find the "POST - Create Connector" request in the imported collection
   - Update the request body if needed:
   ```json
   {
     "name": "postgres-connector",
     "config": {
       "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
       "database.hostname": "datalake",
       "database.port": "5432",
       "database.user": "admin",
       "database.password": "admin123",
       "database.dbname": "busdb",
       "database.server.name": "datalake",
       "table.include.list": "public.test_users", 
       "plugin.name": "pgoutput",
       "tombstones.on.delete": "false",
       "include.schema.changes": "false"
     }
   }
   ```
   - Send the POST request to create the connector

3. **Verify Connector Status:**
   - Use the "GET - List All Connectors" request
   - Check that your connector appears in the list
   - Use "GET - Connector Status" to verify it's running

### Step 4: Insert Test Data

Go back to your PostgreSQL session and insert more data to trigger change events:

```sql
-- Insert new records
INSERT INTO test_users (name, email) VALUES 
    ('Alice Johnson', 'alice@example.com'),
    ('Bob Wilson', 'bob@example.com');

-- Update existing record
UPDATE test_users SET name = 'John Updated' WHERE id = 1;

-- Delete a record
DELETE FROM test_users WHERE id = 2;

-- Insert more test data
INSERT INTO test_users (name, email) VALUES 
    ('Charlie Brown', 'charlie@example.com'),
    ('Diana Prince', 'diana@example.com');
```

### Step 5: View Messages in Kafka UI (New Terminal)

Open another new terminal and port forward Kafka UI:

```bash
# Port forward Kafka UI
kubectl port-forward -n batch service/kafka-ui 8082:8082
```

Then:
1. Open your browser and go to `http://localhost:8082`(admin/admin123)
2. Navigate to **Topics** section
3. Look for topics related to your PostgreSQL connector:
   - `datalake.public.test_users` (main topic)
   - `connect_configs`
   - `connect_offsets`
   - `connect_status`

4. Click on the `postgres-server.public.test_users` topic
5. Go to the **Messages** tab
6. You should see change events for:
   - Initial snapshot of existing data
   - INSERT operations
   - UPDATE operations  
   - DELETE operations

### Expected Results

You should see messages in Kafka that look like:
- **INSERT**: Shows the new record data
- **UPDATE**: Shows both "before" and "after" values
- **DELETE**: Shows the deleted record data

### Troubleshooting Pipeline Issues

If you don't see messages in Kafka:

1. **Check Connector Status:**
   ```bash
   curl http://localhost:8083/connectors/postgres-connector/status
   ```

2. **Check Connector Logs:**
   ```bash
   kubectl logs -n batch deployment/debezium-connect
   ```

3. **Verify PostgreSQL Configuration:**
   ```sql
   -- Check if logical replication is enabled
   SHOW wal_level;
   -- Should be 'logical'
   
   -- Check replication slots
   SELECT * FROM pg_replication_slots;
   ```

4. **Check Kafka Topics:**
   ```bash
   # Port forward Kafka and list topics
   kubectl port-forward -n batch service/kafka-broker-1 9092:9092
   # Then use kafka tools to list topics
   ```

## Accessing Other Services

### Port Forward to Access Services Locally(Open in new termianal)

#### Access Minio
```bash
kubectl port-forward -n batch service/minio 9000:9000 9001:9001
# Open http://localhost:9000 in your browser(minio/minio123)
```

## Troubleshooting

### Check Pod Events
```bash
kubectl get events -n batch --sort-by=.metadata.creationTimestamp
```

### Debug Specific Pod
```bash
# Describe pod to see events and status
kubectl describe pod -n batch <pod-name>

# Get pod logs
kubectl logs -n batch <pod-name>

# Execute commands in pod
kubectl exec -it -n batch <pod-name> -- /bin/bash
```

## Clean Up

### Delete All Resources
```bash
# Delete the entire namespace (removes all resources)
kubectl delete namespace batch
```

### Stop Minikube
```bash
minikube stop
```

## Architecture Overview

The deployment includes:

- **Zookeeper**: Coordination service for Kafka
- **Kafka**: Message broker for data streaming
- **Schema Registry**: Schema management for Kafka messages
- **Kafka UI**: Web interface for Kafka management
- **Debezium Connect**: Change data capture connector
- **PostgreSQL**: Database with Debezium extensions
- **Minio**: S3-compatible object storage
- **Datalake**: Data processing components

## Environment Variables

Key environment configurations are set in the deployment files:

- Kafka brokers connect to Zookeeper at `zookeeper-1:2181`
- Schema Registry is accessible at `http://schema-registry:8081`
- Kafka broker internal communication on port `29092`
- External Kafka access on port `9092`

## Notes

- Wait for each component to be ready before deploying the next one
- All services are deployed in the `batch` namespace
- Use `kubectl logs` to check for any startup issues
- Health checks are configured for most services