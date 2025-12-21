#!/bin/bash
set -e

# Check if image tag is provided
if [ -z "$1" ]; then
    echo "Error: Image tag not provided"
    echo "Usage: $0 <image_tag>"
    exit 1
fi

IMAGE_TAG="$1"

echo "Building images with tag: $IMAGE_TAG"

# Build Spark image
echo "Building Spark image..."
docker build -t "py-spark-spark:$IMAGE_TAG" -f ./batch/Dockerfile.spark ../

# Build Airflow image (depends on Spark image)
echo "Building Airflow image..."
docker build --build-arg PY_SPARK_VERSION="$IMAGE_TAG" -t "py-spark-airflow:$IMAGE_TAG" -f ./airflow/Dockerfile.airflow ../

# Build Flink image
echo "Building Flink image..."
docker build -t "flink-bus-job:1.0" -f ./stream/Dockerfile.flink ../

echo "All images built successfully!"