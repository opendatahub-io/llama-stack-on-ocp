# Monitor Llamastack & vLLM in OpenShift

Follow this README to configure an observability stack in OpenShift to visualize Llamastack telemetry and vLLM metrics.
Llamastack and vLLM also must be configured to generate telemetry.
This [configuration guide](./run-configuration.md) outlines how to update the deployment manifests for telemetry collection.

This [architecture diagram](./diagram-overview.md) provides a visual overview of the components listed below.


## OpenShift Observability Operators

Operators are available from OperatorHub
The following operators must be installed in order to proceed with this example.

### Operator descriptions

1. **Red Hat Build of OpenTelemetry**: The OpenTelemetry Collector (OTC) is provided from this operator.
Metrics and traces will be distributed from the OTC to various backends. Tempo is deployed and is the tracing backend.

2. **Tempo Operator**: Provides `TempoStack` Custom Resource. This is the backend for distributed tracing.
An S3-compatible storage (Minio) is paired with Tempo.

3. **Cluster Observability Operator**: This provides PodMonitor and ServiceMonitor Custom Resources which are necessary for
user-workload monitoring's prometheus to scrape workload metrics. Also, the COO provides UIPlugins for viewing telemetry.

3. **(optional) Grafana Operator**: Provides Grafana APIs including `GrafanaDashboard`, `Grafana`, and `GrafanaDataSource` that will be used to visualize telemetry.

## Create PodMonitor or ServiceMonitor for any AI Workload that exposes a metrics endpoint

This is how to enable collection of user-workload metrics for any workload within OpenShift. You need to create a `PodMonitor` or a `ServiceMonitor`.
The PodMonitor will ensure all metrics from pods with matching selectors will be scraped by the user-workload-monitoring Prometheus, and a ServiceMonitor will
scrape from any pod that runs under a particular service.

* [Example PodMonitor](./podmonitor-example-0.yaml)
* [Example ServiceMonitor](./servicemonitor-example.yaml)

Upon creation of either, metrics will be scraped and will be visible from the console `Observe -> Metrics` dashboards.

## Create custom resources and configurations for a central observability hub

Create the observablity hub namespace `observability-hub`. If a different namespace is created, be sure to update the resource yamls accordingly.

```bash
oc create ns observability-hub
```

### Tracing Backend (Tempo with Minio for S3 storage)

In order to view distributed tracing data from LLamastack and/or vLLM, you must deploy a tracing backend. The supported tracing backend in OpenShift
is Tempo. See the OpenShift Tempo
[documentation](https://docs.redhat.com/en/documentation/openshift_container_platform/4.18/html/distributed_tracing/distributed-tracing-platform-tempo#distr-tracing-tempo-install-tempostack-web-console_dist-tracing-tempo-installing)
for further details. Tempo must be paired with a storage solution. For this example, `MinIO` is used. The necessary resources can be created by
applying the `./tempo` manifests.

```bash
# edit storageclassName & secret as necessary
# secret and storage for testing only
oc apply --kustomize ./tempo -n observability-hub
```

### OpenTelemetryCollector deployment

OpenTelemetry Collector is used to aggregate telemetry from various workloads, process individual signals, and export
to various backends. This example will collect traces from various workloads and export all as a single
authenticated stream to the in-cluster TempoStack. For in-cluster only, opentelemetry-collector is not necessary to collect
metrics. Metrics are sent to the in-cluster user-workload-monitoring prometheus by creating podmonitors and/or servicemonitors.
However, if exporting off-cluster to a 3rd party observability vendor, the collector is necessary for all signals,
and can provide a single place with which to receive telemetry from various workloads and export as a single authenticated and
secure OTLP stream. OpenTelemetryCollector Sidecars and TargetAllocators are also explained below.

> **📝 NOTE:** If you are only concerned with metrics, and only want to view them within the cluster with Grafana or
> in the OpenShift console, you do not need to use the OpenTelemetryCollector. PodMonitors and ServiceMonitors
> paired with OpenShift's user workload monitoring Prometheus instance is all that's necessary.

#### Central OpenTelemetry Collector

To create a central opentelemetry-collector, update the
[otel-collector/otel-collector.yaml](./otel-collector/otel-collector.yaml) to match your requirements and then apply.

```bash
oc apply --kustomize ./otel-collector -n observability-hub
```

#### OpenTelemetryCollector TargetAllocators

You can add individual metrics endpoints to the central otel-collector in observability-hub, but
a simpler way is to create a TargetAllocator to utilize already-existing PodMonitors and ServiceMonitors to configure
an OpenTelemetryCollector's Prometheus receiver scrape targets. A TargetAllocator within an OpenTelemetryCollector will
gather Prometheus scrape target endpoints from PodMonitors and ServiceMonitors.
An example of an OpenTelemetryCollector with a TargetAllocator is
[otel-collector target-allocator](./otel-collector/otel-collector-target-allocator.yaml). Note that when using TargetAllocators,
the OpenTelemetryCollector must be set to `StatefulSet` mode.

#### OpenTelemetryCollector Sidecars

You can add individual metrics endpoints to the central otel-collector in observability-hub, but
another way is to add otel-collector sidecar containers to individual deployments throughout the
cluster. Paired with an annotation on the deployment, telemetry will be exported as configured.

For an example, any deployment with the `template.metadata.annotations` `sidecar.opentelemetry.io/inject: vllm-otelsidecar`
will receive and export telemetry as configured in the
[otel-collector-vllm-sidecar example](./otel-collector/otel-collector-vllm-sidecar.yaml).

Similarly, any deployment with the `template.metadata.annotations` `sidecar.opentelemetry.io/inject: llamastack-otelsidecar`
will receive and export telemetry as configured in the
[otel-collector-llamstack-sidecar example](./otel-collector/otel-collector-llamastack-sidecar.yaml).


### Cluster Observability Operator Tracing UIPlugin

OpenShift provides a Tracing UI and Dashboards similar to how it provides a prometheus metrics explorer with user-workload-monitoring.
The Jaeger frontend feature of TempoStack is no longer supported by Red Hat. This has been replaced by the COO UIPlugin.
To create the `UIPlugin for Distributed Tracing`, first ensure the TempoStack described above is created. This is a prerequisite. Then, all that's necessary to view traces from
the OpenShift console at `Observe -> Traces` is to create the following [Tracing UIPlugin resource](./tracing-ui-plugin.yaml).

```bash
oc apply ./tracing-ui-plugin.yaml
```

You should now see traces and metrics in the OpenShift console, from the `Oberve` tab.

### Grafana

Most users are familiar with Grafana for visualizing and analyzing telemetry. To create the Grafana resources necessary to view
Llamastack and vLLM telemetry, follow the below example.

This example will deploy a Grafana instance, and Prometheus & Tempo DataSources
The prometheus datasource is the user-workload-monitoring prometheus running in `openshift-user-workload-monitoring` namespace.
The Grafana console is configured with `username: rhel, password: rhel`

```bash
oc apply --kustomize ./grafana/instance-with-prom-tempo-ds
```

Upon success, you can explore metrics and traces from Grafana route.

#### GrafanaDashboards to visualize cluster and vLLM metrics

##### vLLM

To create a `vLLM` GrafanaDashboard, run

```bash
oc apply -n observability-hub -f vllml-dashboard/vllm-dashboard.yaml
```

You should now see a dashboard named `vLLM` in the Grafana console by choosing `Dashboards` from the left navigation bar.

##### Cluster-Metrics

For another dashboard, check out [github.com/kevchu3/openshift-4-grafana](https://github.com/kevchu3/openshift4-grafana/tree/master/dashboards/crds) for a list of
dashboards to deploy on OpenShift.

This [dashboard](./grafana/cluster-metrics-dashboard/cluster_metrics.ocp.json) is slightly modified from
https://github.com/kevchu3/openshift4-grafana/blob/master/dashboards/json_raw/cluster_metrics.ocp416.json

```bash
oc apply -n observability-hub -f cluster-metrics-dashboard/cluster-metrics.yaml
```

You should now see a dashboard named `cluster-metrics` in the Grafana console by choosing `Dashboards` from the left navigation bar.
