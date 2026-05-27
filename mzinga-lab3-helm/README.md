# MZinga Lab 3 Helm Chart

This chart packages the Lab 3 stack so it can be installed later as one Helm release:

- MZinga Apps
- Observable email worker
- Jaeger
- Optional MailHog
- Bitnami MongoDB, RabbitMQ, and Redis dependencies

The chart is prepared only as source. The dependency archives are not committed; run `helm dependency update ./mzinga-lab3-helm` when you are ready to install.

## Prepare The Worker Image

Build and load the worker image into minikube before installing the chart:

```sh
docker build -t lab3-email-worker:1.0.0 ./lab3/lab3-worker-observable
minikube image load lab3-email-worker:1.0.0
```

The default worker image pull policy is `Never`, because the lab image is local.

## Preview Later

When you want to preview the rendered YAML without installing anything:

```sh
helm template mzinga-lab3 ./mzinga-lab3-helm \
  --namespace mzinga \
  --set emailWorker.credentials.email="worker@example.com" \
  --set emailWorker.credentials.password="test"
```

## Install Later

```sh
helm dependency update ./mzinga-lab3-helm

helm install mzinga-lab3 ./mzinga-lab3-helm \
  --namespace mzinga \
  --create-namespace \
  --set emailWorker.credentials.email="worker@example.com" \
  --set emailWorker.credentials.password="yourpassword" \
  --timeout 5m \
  --wait
```

## Useful Port Forwards

```sh
kubectl port-forward service/mzinga-lab3-mzinga-apps 3000:3000 -n mzinga
kubectl port-forward service/mzinga-lab3-jaeger 16686:16686 -n mzinga
kubectl port-forward service/mzinga-lab3-mailhog 8025:8025 -n mzinga
```

## Notes

- `emailWorker.credentials.email` and `emailWorker.credentials.password` are required and stored in a Kubernetes Secret.
- `mailhog.enabled` defaults to `true` for the lab. Disable it and set `emailWorker.env.smtpHost` when using an external SMTP server.
- `mzingaApps.env.communicationsExternalWorker` defaults to `"true"` so MZinga writes `status: pending` and the worker can process communications asynchronously.
- `mzingaApps.env.hooksUrlCommunicationsAfterChange` is empty by default because the Lab 3 worker polls the REST API. Set it to `"rabbitmq"` when pairing the chart with an event-driven worker.
