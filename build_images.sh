set -e

# expects to receive image tag as first argument
docker build -t "py-spark-spark:$1" -f Dockerfile.spark .
docker build --build-arg PY_SPARK_VERSION="$1" -t "py-spark-airflow:$1" -f Dockerfile.airflow .