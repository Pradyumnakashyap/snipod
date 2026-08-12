{{- define "snipod.fullname" -}}
{{ .Release.Name }}
{{- end -}}

{{- define "snipod.labels" -}}
app: {{ include "snipod.fullname" . }}
app.kubernetes.io/name: snipod
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "snipod.selectorLabels" -}}
app: {{ include "snipod.fullname" . }}
{{- end -}}
