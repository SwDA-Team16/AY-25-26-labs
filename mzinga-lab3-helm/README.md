# MZinga Lab 3 Helm Chart

This chart packages the Lab 3 stack so it can be installed later as one Helm release:

- MZinga Apps
- Observable email worker
- Optional RabbitMQ event bus for the event-driven worker
- Jaeger
- Optional MailHog
- Bitnami MongoDB dependency

The chart is prepared only as source. The dependency archives are not committed; run `helm dependency update ./mzinga-lab3-helm` when you are ready to install.

## Prepare The Worker Image

Build and load the MZinga and worker images into minikube before installing the chart:

```sh
docker build -t mzinga-apps:local -f ./mzinga/mzinga-apps/backoffice.Dockerfile ./mzinga/mzinga-apps
docker build -t lab3-email-worker:1.0.0 ./lab3/lab3-worker-observable
minikube image load mzinga-apps:local
minikube image load lab3-email-worker:1.0.0
```

The default MZinga and worker image pull policies are `Never`, because both lab images are local.

## REST API Polling Worker

The default worker mode is `polling`. In this mode, MZinga does not publish RabbitMQ events. Instead, it saves the Communication, the collection hook sets `status: pending`, and the worker periodically calls the MZinga REST API:

```text
GET /api/communications?where[status][equals]=pending&depth=1
GET /api/communications/:id?depth=1
PATCH /api/communications/:id
```

Because the worker fetches documents with `depth=1`, relationship fields such as `tos`, `ccs`, and `bccs` already contain resolved user objects. The worker can read `value.email` directly and does not need a MongoDB connection string or a separate users query.

Build and load the polling worker image:

```sh
docker build -t lab3-email-worker:1.1.0 ./lab3/lab3-worker-observable
minikube image load lab3-email-worker:1.1.0
```

Deploy or upgrade the release in polling mode:

```sh
helm upgrade mzinga-lab3 ./mzinga-lab3-helm \
  --namespace mzinga \
  --set rabbitmq.enabled=false \
  --set emailWorker.mode=polling \
  --set emailWorker.image.repository=lab3-email-worker \
  --set emailWorker.image.tag=1.1.0 \
  --set mzingaApps.env.hooksUrlCommunicationsAfterChange="" \
  --set mzingaApps.env.publicServerUrl=http://localhost:3000 \
  --set emailWorker.credentials.email="worker@example.com" \
  --set emailWorker.credentials.password="yourpassword" \
  --rollback-on-failure \
  --wait \
  --timeout 5m
```

This mode is simple and useful for the REST API lab, but it should generally stay at `emailWorker.replicaCount=1`. Multiple polling replicas can observe the same pending document unless the application adds an atomic claim/lock step.

## RabbitMQ Event-Driven Worker

Build and load the RabbitMQ worker variant when you want MZinga to publish `afterChange` events to RabbitMQ instead of relying on REST polling:

```sh
docker build -t lab3-email-worker-rabbitmq:1.0.2 ./lab3/lab3-worker-rabbitmq-observable
docker pull rabbitmq:3-management
docker pull busybox:1.36
minikube image load lab3-email-worker-rabbitmq:1.0.2
minikube image load rabbitmq:3-management
minikube image load busybox:1.36
```

Upgrade the release into RabbitMQ mode:

```sh
helm upgrade mzinga-lab3 ./mzinga-lab3-helm \
  --namespace mzinga \
  --set rabbitmq.enabled=true \
  --set emailWorker.mode=rabbitmq \
  --set emailWorker.image.repository=lab3-email-worker-rabbitmq \
  --set emailWorker.image.tag=1.0.2 \
  --set mzingaApps.env.hooksUrlCommunicationsAfterChange=rabbitmq \
  --set mzingaApps.env.publicServerUrl=http://localhost:3000 \
  --set emailWorker.credentials.email="worker@example.com" \
  --set emailWorker.credentials.password="yourpassword" \
  --rollback-on-failure \
  --wait \
  --timeout 5m
```

The worker listens on queue `communications-email-worker`, bound to exchange `mzinga_events_durable` with routing key `HOOKSURL_COMMUNICATIONS_AFTERCHANGE`.

Scale only the RabbitMQ mode worker horizontally:

```sh
helm upgrade mzinga-lab3 ./mzinga-lab3-helm \
  --namespace mzinga \
  --set rabbitmq.enabled=true \
  --set emailWorker.mode=rabbitmq \
  --set emailWorker.replicaCount=5 \
  --set emailWorker.image.repository=lab3-email-worker-rabbitmq \
  --set emailWorker.image.tag=1.0.2 \
  --set mzingaApps.env.hooksUrlCommunicationsAfterChange=rabbitmq \
  --set mzingaApps.env.publicServerUrl=http://localhost:3000 \
  --set emailWorker.credentials.email="worker@example.com" \
  --set emailWorker.credentials.password="yourpassword"
```

## What Changed In The Helm Chart

The chart started as a simple deployment for MZinga, MongoDB, Jaeger, MailHog, and one email worker. During the lab we changed the YAML templates so the same chart can deploy either the REST polling worker or the RabbitMQ event-driven worker.

In `values.yaml`, the worker now has an explicit mode:

```yaml
emailWorker:
  mode: "polling"
```

This is used to distinguish the default REST polling setup from RabbitMQ mode. Polling mode only needs MZinga REST credentials and SMTP settings. RabbitMQ mode also needs queue configuration:

```yaml
emailWorker:
  env:
    rabbitmqUrl: ""
    routingKey: "HOOKSURL_COMMUNICATIONS_AFTERCHANGE"
    exchangeName: "mzinga_events_durable"
    queueName: "communications-email-worker"
```

The chart also gained an optional RabbitMQ section:

```yaml
rabbitmq:
  enabled: false
  image:
    repository: rabbitmq
    tag: "3-management"
  service:
    amqpPort: 5672
    managementPort: 15672
```

This keeps RabbitMQ disabled by default, so the REST polling lab remains lightweight. When `rabbitmq.enabled=true`, the chart renders:

```text
templates/rabbitmq-deployment.yaml
templates/rabbitmq-service.yaml
```

The RabbitMQ `Deployment` runs the broker, and the `Service` exposes port `5672` for AMQP plus `15672` for the management UI.

The helper template `_helpers.tpl` now builds the internal RabbitMQ URL:

```text
amqp://guest:guest@mzinga-lab3-rabbitmq:5672/
```

This avoids hardcoding the release name in multiple templates. If a custom `emailWorker.env.rabbitmqUrl` is provided, the chart uses that instead.

The MZinga Apps Deployment now conditionally receives RabbitMQ settings:

```yaml
- name: RABBITMQ_URL
  value: amqp://guest:guest@mzinga-lab3-rabbitmq:5672/
- name: HOOKSURL_COMMUNICATIONS_AFTERCHANGE
  value: rabbitmq
```

These two variables are what make MZinga publish the Communications `afterChange` hook to RabbitMQ. Without `RABBITMQ_URL`, MZinga cannot connect to the broker. Without `HOOKSURL_COMMUNICATIONS_AFTERCHANGE=rabbitmq`, the Communications collection does not publish that hook event.

The MZinga Apps Deployment also got a small init container when RabbitMQ is enabled:

```yaml
initContainers:
  - name: wait-for-rabbitmq
```

Its job is to wait until the RabbitMQ service accepts TCP connections before MZinga starts. This reduces the chance that MZinga boots before RabbitMQ is available and skips setting up its message bus connection.

The email worker Deployment now conditionally receives RabbitMQ variables only in RabbitMQ mode:

```yaml
- name: RABBITMQ_URL
- name: ROUTING_KEY
- name: EXCHANGE_NAME
- name: QUEUE_NAME
```

This keeps the same Kubernetes `Deployment` template reusable. In polling mode, the worker only polls the REST API. In RabbitMQ mode, the worker subscribes to the queue and processes one event per delivered message.

Finally, `mzingaApps.env.publicServerUrl` was set to:

```yaml
publicServerUrl: "http://localhost:3000"
```

This fixes the admin UI when using `kubectl port-forward`. The browser runs on your laptop, not inside Kubernetes, so it must call `localhost:3000`; it cannot resolve internal Kubernetes names such as `mzinga-lab3-mzinga-apps:3000`.

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
kubectl port-forward service/mzinga-lab3-rabbitmq 15672:15672 -n mzinga
```

## Console Output From Our Run

These are the important outputs observed while developing and deploying the chart locally. Long Docker layer download logs are intentionally shortened to the final success lines.

### Minikube

```text
$ minikube start --driver=docker --cpus=2 --memory=4096
Done! kubectl is now configured to use "minikube" cluster and "default" namespace by default

$ kubectl cluster-info
Kubernetes control plane is running at https://127.0.0.1:53310
CoreDNS is running at https://127.0.0.1:53310/api/v1/namespaces/kube-system/services/kube-dns:dns/proxy
```

### Initial Chart Health

```text
$ helm lint mzinga-lab3-helm
==> Linting mzinga-lab3-helm
[INFO] Chart.yaml: icon is recommended

1 chart(s) linted, 0 chart(s) failed
```

The first broken install attempt exposed stale remote image/dependency choices. Later revisions switched to local images and a current MongoDB chart.

```text
Failed to pull image "newesissrl.azurecr.io/mzinga/payload/gh/backoffice:0.9.3"
Failed to pull image "docker.io/bitnami/mongodb:7.0.14-debian-12-r3"
Failed to pull image "docker.io/bitnami/rabbitmq:3.13.7-debian-12-r2"
```

### Public URL Fix

The browser initially tried to call the internal Kubernetes DNS name:

```text
mzinga-lab3-mzinga-apps:3000/api/users/me
Failed to load resource: net::ERR_NAME_NOT_RESOLVED
```

After setting `mzingaApps.env.publicServerUrl=http://localhost:3000`, the rendered Deployment had the correct browser-facing URLs:

```text
$ kubectl get deployment mzinga-lab3-mzinga-apps -n mzinga -o jsonpath='...'
http://localhost:3000
http://localhost:3000
```

### Polling Worker Success

After enabling the original REST polling worker, Kubernetes reported the worker as ready:

```text
$ kubectl get pods -n mzinga
NAME                                        READY   STATUS    RESTARTS   AGE
mzinga-lab3-email-worker-7866cbddd6-fjmf7   1/1     Running   0          13s
mzinga-lab3-jaeger-64dc99564c-4z8pw         1/1     Running   0          7m46s
mzinga-lab3-mailhog-8679fd7687-bblgn        1/1     Running   0          7m46s
mzinga-lab3-mongodb-967b56f6-j8cq7          1/1     Running   0          7m46s
mzinga-lab3-mzinga-apps-757bd8df85-7pbxc    1/1     Running   0          2m52s
```

The worker processed a Communication and patched it to `sent`:

```text
{"service": "email-worker", "event": "processing_started", "doc_id": "6a2283682d41d7f0a8fbd327", "level": "info"}
{"service": "email-worker", "status": "sent", "event": "processing_completed", "doc_id": "6a2283682d41d7f0a8fbd327", "level": "info"}
```

MailHog contained the email:

```text
$ kubectl exec -n mzinga deployment/mzinga-lab3-mailhog -- wget -qO- http://127.0.0.1:8025/api/v2/messages
{"total":1,"count":1,...,"Subject":["prova"],"To":["admin@email.com"],"Body":"prova su k8s"...}
```

### Worker Image Upgrade

The polling worker image was rebuilt as `1.1.0`, loaded into minikube, and deployed with Helm:

```text
$ docker build -t lab3-email-worker:1.1.0 ./lab3/lab3-worker-observable
naming to docker.io/library/lab3-email-worker:1.1.0 done

$ minikube image load lab3-email-worker:1.1.0

$ helm upgrade mzinga-lab3 ./mzinga-lab3-helm --namespace mzinga --set-string emailWorker.image.tag=1.1.0 ...
Release "mzinga-lab3" has been upgraded. Happy Helming!
REVISION: 4
STATUS: deployed
```

Kubernetes confirmed the new tag:

```text
$ kubectl get deployment mzinga-lab3-email-worker -n mzinga -o jsonpath='...'
lab3-email-worker:1.1.0
1/1 ready
```

### RabbitMQ Worker Build

The event-driven worker image was built and loaded:

```text
$ docker build -t lab3-email-worker-rabbitmq:1.0.2 ./lab3/lab3-worker-rabbitmq-observable
naming to docker.io/library/lab3-email-worker-rabbitmq:1.0.2 done

$ minikube image load lab3-email-worker-rabbitmq:1.0.2
```

### Rollback-On-Failure In Action

An intermediate RabbitMQ worker image missed a dependency and failed to start:

```text
Traceback (most recent call last):
  File "/app/worker.py", line 15, in <module>
    from opentelemetry.exporter.prometheus import PrometheusMetricReader
ModuleNotFoundError: No module named 'opentelemetry.exporter.prometheus'
```

Helm detected the failed rollout and rolled the release back:

```text
level=WARN msg="upgrade failed" name=mzinga-lab3 error="resource Deployment/mzinga/mzinga-lab3-email-worker not ready..."
Error: UPGRADE FAILED: release mzinga-lab3 failed, and has been rolled back due to rollback-on-failure being set
```

The fixed image `1.0.2` also added RabbitMQ connection retry logic, avoiding startup races when AMQP was not ready yet:

```text
ConnectionRefusedError: [Errno 111] Connect call failed
```

### Final RabbitMQ Deployment

The final RabbitMQ-mode upgrade completed as revision 8:

```text
$ helm upgrade mzinga-lab3 ./mzinga-lab3-helm --namespace mzinga ... --set emailWorker.image.tag=1.0.2
Release "mzinga-lab3" has been upgraded. Happy Helming!
REVISION: 8
STATUS: deployed
```

All pods were healthy:

```text
$ kubectl get pods -n mzinga
NAME                                       READY   STATUS    RESTARTS   AGE
mzinga-lab3-email-worker-7c9b8cf86-4zkvd   1/1     Running   0          78s
mzinga-lab3-jaeger-64dc99564c-4z8pw        1/1     Running   0          28m
mzinga-lab3-mailhog-8679fd7687-bblgn       1/1     Running   0          28m
mzinga-lab3-mongodb-967b56f6-j8cq7         1/1     Running   0          28m
mzinga-lab3-mzinga-apps-cf9b9d6b-zb2q6     1/1     Running   0          3m3s
mzinga-lab3-rabbitmq-7986d4fb78-76txf      1/1     Running   0          3m3s
```

The worker was running the RabbitMQ image:

```text
$ kubectl get deployment mzinga-lab3-email-worker -n mzinga -o jsonpath='...'
lab3-email-worker-rabbitmq:1.0.2
1/1 ready
```

The worker logs showed successful authentication, RabbitMQ connection, and queue subscription:

```text
{"service": "email-worker", "event": "authenticated_with_mzinga_api", "level": "info"}
{"service": "email-worker", "event": "connected_to_rabbitmq", "level": "info"}
{"service": "email-worker", "exchange": "mzinga_events_durable", "queue": "communications-email-worker", "routing_key": "HOOKSURL_COMMUNICATIONS_AFTERCHANGE", "event": "worker_started", "level": "info"}
```

MZinga had the expected RabbitMQ hook environment:

```text
$ kubectl get deployment mzinga-lab3-mzinga-apps -n mzinga -o jsonpath='...'
amqp://guest:guest@mzinga-lab3-rabbitmq:5672/
rabbitmq
```

RabbitMQ bindings proved the event path was wired:

```text
$ kubectl exec -n mzinga deployment/mzinga-lab3-rabbitmq -- rabbitmqctl list_bindings source_name destination_name routing_key
Listing bindings for vhost /...
source_name              destination_name              routing_key
                         communications-email-worker   communications-email-worker
mzinga_events            mzinga_events_durable          #
mzinga_events_durable    communications-email-worker   HOOKSURL_COMMUNICATIONS_AFTERCHANGE
```

The Helm history captured the failed upgrade, rollback, and final deployed revision:

```text
$ helm history mzinga-lab3 -n mzinga
REVISION  STATUS      DESCRIPTION
4         superseded  Upgrade complete
5         failed      Upgrade "mzinga-lab3" failed: resource Deployment/mzinga/mzinga-lab3-email-worker not ready...
6         superseded  Rollback to 4
7         superseded  Upgrade complete
8         deployed    Upgrade complete
```

## Notes

- `emailWorker.credentials.email` and `emailWorker.credentials.password` are required and stored in a Kubernetes Secret.
- `mailhog.enabled` defaults to `true` for the lab. Disable it and set `emailWorker.env.smtpHost` when using an external SMTP server.
- `mzingaApps.env.communicationsExternalWorker` defaults to `"true"` so MZinga writes `status: pending` and the worker can process communications asynchronously.
- `mzingaApps.env.hooksUrlCommunicationsAfterChange` is empty by default because the Lab 3 worker polls the REST API. Set it to `"rabbitmq"` when pairing the chart with an event-driven worker.
