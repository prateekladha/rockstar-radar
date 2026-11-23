{{- define "rockstar.labels" -}}
app.kubernetes.io/name: rockstar-radar
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{- define "rockstar.image" -}}
{{ .Values.image.repository }}:{{ .Values.image.tag }}
{{- end -}}

{{/* Env shared by both pods: DB, secrets (from the synced k8s Secret), public config. */}}
{{- define "rockstar.commonEnv" -}}
- { name: APP_OCI_AUTH, value: instance_principal }
- { name: OCI_REGION, value: {{ .Values.oci.region | quote }} }
- { name: PUBLIC_BASE_URL, value: {{ .Values.publicBaseUrl | quote }} }
- name: DB_DSN
  valueFrom: { secretKeyRef: { name: rockstar-secrets, key: db-dsn } }
- name: DB_APP_PASSWORD
  valueFrom: { secretKeyRef: { name: rockstar-secrets, key: db-app-password } }
- name: ENCRYPTION_KEY
  valueFrom: { secretKeyRef: { name: rockstar-secrets, key: encryption-key } }
- name: SESSION_SECRET
  valueFrom: { secretKeyRef: { name: rockstar-secrets, key: session-secret } }
- name: GOOGLE_CLIENT_ID
  valueFrom: { secretKeyRef: { name: rockstar-secrets, key: google-client-id } }
- name: GOOGLE_CLIENT_SECRET
  valueFrom: { secretKeyRef: { name: rockstar-secrets, key: google-client-secret } }
- name: INTERNAL_TOKEN
  valueFrom: { secretKeyRef: { name: rockstar-secrets, key: internal-token } }
{{- end -}}

{{- define "rockstar.podSecurity" -}}
securityContext:
  runAsNonRoot: true
  runAsUser: 10001
  fsGroup: 10001
  seccompProfile: { type: RuntimeDefault }
{{- end -}}

{{- define "rockstar.containerSecurity" -}}
securityContext:
  allowPrivilegeEscalation: false
  capabilities: { drop: ["ALL"] }
{{- end -}}
