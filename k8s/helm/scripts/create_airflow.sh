#!/bin/bash

NAMESPACE=$1
TAG=$2

helm repo add apache-airflow https://airflow.apache.org

mkdir -p "$HELM_BASE_DIR/airflow"

cat > "$HELM_BASE_DIR/airflow/values.yaml" << EOF
executor: KubernetesExecutor
airflowVersion: "3.1.0"
# migrateDatabaseJob:
#   enabled: true
#   ttlSecondsAfterFinished: 300
images:
  airflow:
    repository: py-spark-airflow
    tag: $TAG
    pullPolicy: IfNotPresent

# Create an admin user on first install
# webserver:
#   defaultUser:
#     username: admin
#     password: admin
#     role: Admin
#     email: admin@example.com
#     firstName: First Name
#     lastName: Last Name

env:
  - name: SPARK_MASTER_URL
    value: "k8s://https://kubernetes.default.svc:443"
  - name: SPARK_IMAGE_VERSION
    value: "$TAG"
  - name: AIRFLOW_CONN_KUBERNETES_DEFAULT
    value: "kubernetes://?extra__kubernetes__in_cluster=true"
  - name: AIRFLOW__SECRETS__SENSITIVE_FIELDS
    value: "AWS_SECRET_ACCESS_KEY,AWS_ACCESS_KEY_ID"
  - name: AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION
    value: "True"
  - name: AIRFLOW__CORE__LOAD_EXAMPLES
    value: "False"
  - name: AIRFLOW__SCHEDULER__ENABLE_HEALTH_CHECK
    value: "True"
#   - name: AIRFLOW__CORE__ENABLE_XCOM_PICKLING
#     value: "True"
#   - name: AIRFLOW__CORE__AUTH_MANAGER
#     value: "airflow.providers.fab.auth_manager.fab_auth_manager.FabAuthManager"
#   - name: AIRFLOW__FAB__SESSION_BACKEND
#     value: "securecookie"
  - name: AIRFLOW__CORE__DEFAULT_TIMEZONE
    value: "Asia/Jerusalem"
  - name: AIRFLOW__CORE__EXECUTION_API_SERVER_URL
    value: "http://airflow-api-server:8080/execution/"
  - name: TZ
    value: "Asia/Jerusalem"
  - name: SPARK_HOME
    value: "/opt/spark"
  - name: SPARK_CONNECTION_METHOD
    value: "session"
  - name: SPARK_CONN_HOST
    value: "k8s://https://kubernetes.default.svc"
  - name: SPARK_CONN_PORT
    value: "443"
  - name: STORAGE_BUCKET
    value: bus-sensor-data
  - name: STORAGE_ENDPOINT
    value: https://cuong-dev.cloud:9000
  - name: STORAGE_ENDPOINT_SSL_ENABLE
    value: "true"
  - name: AWS_ACCESS_KEY_ID
    value: minio
  - name: AWS_SECRET_ACCESS_KEY
    value: minio123
  - name: STORAGE_PATH_STYLE_ACCESS
    value: "true"
  - name: AWS_REGION
    value: us-east-1
  - name: AIRFLOW__WEBSERVER__SECRET_KEY
    value: "vanh"
  - name: AIRFLOW__API__AUTH_JWT_SECRET
    value: "vanh"

# enableBuiltInSecretEnvVars:
#   AIRFLOW__CORE__FERNET_KEY: true
#   AIRFLOW__CORE__SQL_ALCHEMY_CONN: true
#   AIRFLOW__DATABASE__SQL_ALCHEMY_CONN: false
#   AIRFLOW_CONN_AIRFLOW_DB: false
#   AIRFLOW__API__SECRET_KEY: true
#   AIRFLOW__API_AUTH__JWT_SECRET: true
#   AIRFLOW__WEBSERVER__SECRET_KEY: true
#   AIRFLOW__CELERY__CELERY_RESULT_BACKEND: false
#   AIRFLOW__CELERY__RESULT_BACKEND: false
#   AIRFLOW__CELERY__BROKER_URL: false
#   AIRFLOW__ELASTICSEARCH__HOST: false
#   AIRFLOW__ELASTICSEARCH__ELASTICSEARCH_HOST: false
#   AIRFLOW__OPENSEARCH__HOST: false

# Webserver exposure (NodePort for quick local access; swap to Ingress for production)
web:
  service:
    type: ClusterIP
    externalPort: 8080
scheduler:
  replicas: 1
triggerer:
  enabled: true
  replicas: 1
redis:
  enabled: false
statsd:
  enabled: false
postgresql:
  enabled: true    
  image:
    repository: bitnamilegacy/postgresql
    tag: "13.2.0"
    auth:
      enablePostgresUser: true

workers:
  serviceAccount:
    create: true

# Persist Airflow logs (compose mounted ./logs)
logs:
  persistence:
    enabled: true
    size: 2Gi

config:
  core:
    parallelism: 2
    max_active_tasks_per_dag: 1

# Optional: add plugins volume (compose mounted ./plugins). You can manage plugins in your image instead.
#plugins:
#  persistence:
#    enabled: true
#    size: 1Gi
EOF

helm upgrade --install airflow apache-airflow/airflow --namespace "$NAMESPACE" --create-namespace --values "$HELM_BASE_DIR/airflow/values.yaml"

echo "Applying RBAC permissions for Airflow to manage Spark jobs..."

# 1. Create a Role that grants ONLY the permissions needed to manage SparkApplication resources.
# This follows the principle of least privilege for better security.
cat <<EOF | kubectl apply -f -
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: airflow-spark-manager
  namespace: $NAMESPACE
rules:
  - apiGroups: ["sparkoperator.k8s.io"]
    resources: ["sparkapplications", "sparkapplications/status"]
    verbs: ["create", "get", "list", "watch", "delete", "patch", "update"]
  - apiGroups: [""]
    resources: ["pods", "pods/log", "configmaps", "services", "persistentvolumeclaims"]
    verbs: ["create", "get", "watch", "list", "delete", "patch", "update", "deletecollection"]
  - apiGroups: [""]
    resources: ["events"]
    verbs: ["create", "patch", "update"]
EOF

# 2. Create a RoleBinding to grant the above Role to the Airflow worker's service account.
cat <<EOF | kubectl apply -f -
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: airflow-spark-manager-binding
  namespace: $NAMESPACE
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: airflow-spark-manager
subjects:
- kind: ServiceAccount
  name: airflow-worker
  namespace: $NAMESPACE
EOF

set +e
PORT_BUSY=$(lsof -nP -i ":8080" -a -c kubectl|awk '{print $2}'|sed -n '2p' || true)
if [ -n "$PORT_BUSY" ]; then
  echo "killing $PORT_BUSY"
  kill "$PORT_BUSY"
fi
kubectl port-forward svc/airflow-api-server 8080:8080 --namespace "$NAMESPACE" >/dev/null 2>&1 &
PID=$!
echo "Airflow port-forward PID is $PID"
set -e
