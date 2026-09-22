{{/* Name helpers. */}}

{{- define "meeting-desk.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "meeting-desk.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "meeting-desk.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "meeting-desk.labels" -}}
helm.sh/chart: {{ include "meeting-desk.chart" . }}
{{ include "meeting-desk.selectorLabels" . }}
app.kubernetes.io/version: {{ .Values.image.tag | default .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: meeting-desk
{{- end -}}

{{- define "meeting-desk.selectorLabels" -}}
app.kubernetes.io/name: {{ include "meeting-desk.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "meeting-desk.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "meeting-desk.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "meeting-desk.secretName" -}}
{{- printf "%s-env" (include "meeting-desk.fullname" .) -}}
{{- end -}}

{{- define "meeting-desk.configMapName" -}}
{{- printf "%s-config" (include "meeting-desk.fullname" .) -}}
{{- end -}}

{{- define "meeting-desk.vertexSecretName" -}}
{{- printf "%s-vertex-sa" (include "meeting-desk.fullname" .) -}}
{{- end -}}

{{/*
The env block every pod shares: the non-secret ConfigMap, the Infisical-backed Secret, and the
two build labels that end up on app_build_info.
*/}}
{{- define "meeting-desk.envFrom" -}}
- configMapRef:
    name: {{ include "meeting-desk.configMapName" . }}
{{- if .Values.externalSecrets.enabled }}
- secretRef:
    name: {{ include "meeting-desk.secretName" . }}
{{- end }}
{{- end -}}

{{- define "meeting-desk.commonEnv" -}}
- name: APP_VERSION
  value: {{ .Values.build.version | default .Values.image.tag | quote }}
- name: GIT_COMMIT
  value: {{ .Values.build.commit | quote }}
- name: METRICS_PORT
  value: {{ .Values.containerPorts.metrics | quote }}
- name: POD_NAME
  valueFrom:
    fieldRef:
      fieldPath: metadata.name
{{- if .Values.externalSecrets.vertexServiceAccount.enabled }}
- name: GOOGLE_APPLICATION_CREDENTIALS
  value: {{ printf "%s/%s" .Values.externalSecrets.vertexServiceAccount.mountPath .Values.externalSecrets.vertexServiceAccount.fileName | quote }}
{{- end }}
{{- end -}}

{{/*
readOnlyRootFilesystem means /tmp has to be a volume; the Vertex key is mounted read-only beside
it when it is enabled.
*/}}
{{- define "meeting-desk.volumes" -}}
- name: tmp
  emptyDir: {}
{{- if .Values.externalSecrets.vertexServiceAccount.enabled }}
- name: vertex-sa
  secret:
    secretName: {{ include "meeting-desk.vertexSecretName" . }}
{{- end }}
{{- end -}}

{{- define "meeting-desk.volumeMounts" -}}
- name: tmp
  mountPath: /tmp
{{- if .Values.externalSecrets.vertexServiceAccount.enabled }}
- name: vertex-sa
  mountPath: {{ .Values.externalSecrets.vertexServiceAccount.mountPath }}
  readOnly: true
{{- end }}
{{- end -}}

{{/*
The label selector every alert rule uses. `service` and `namespace` are added by the Prometheus
Operator from the ServiceMonitor's target, not by the app: the six metrics carry only the labels
the standard names.
*/}}
{{- define "meeting-desk.metricSelector" -}}
{{- printf "service=~\"%s(-worker)?\", namespace=\"%s\"" (include "meeting-desk.fullname" .) .Release.Namespace -}}
{{- end -}}
