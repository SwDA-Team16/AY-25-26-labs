{{- define "mzinga-lab3.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "mzinga-lab3.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "mzinga-lab3.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "mzinga-lab3.selectorLabels" -}}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "mzinga-lab3.mongodbUri" -}}
mongodb://{{ include "mzinga-lab3.fullname" . }}-mongodb:27017/mzinga?directConnection=true
{{- end -}}

{{- define "mzinga-lab3.rabbitmqUrl" -}}
amqp://{{ .Values.rabbitmq.auth.username }}:{{ .Values.rabbitmq.auth.password }}@{{ include "mzinga-lab3.fullname" . }}-rabbitmq:5672/
{{- end -}}

{{- define "mzinga-lab3.redisUri" -}}
redis://{{ include "mzinga-lab3.fullname" . }}-redis-master:6379
{{- end -}}

{{- define "mzinga-lab3.smtpHost" -}}
{{- if .Values.emailWorker.env.smtpHost -}}
{{- .Values.emailWorker.env.smtpHost -}}
{{- else if .Values.mailhog.enabled -}}
{{- include "mzinga-lab3.fullname" . }}-mailhog
{{- else -}}
localhost
{{- end -}}
{{- end -}}

