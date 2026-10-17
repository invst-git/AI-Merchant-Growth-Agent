export interface Env {
  DB: D1Database;

  WHATSAPP_TOKEN: string;
  WHATSAPP_PHONE_NUMBER_ID: string;
  WHATSAPP_APP_SECRET: string;
  WHATSAPP_VERIFY_TOKEN: string;
  WHATSAPP_TEMPLATE: string;
  WHATSAPP_TEMPLATE_LANG: string;
  WHATSAPP_ESCALATION_TEMPLATE?: string;
  GRAPH_API_BASE: string;

  PATIENT_WHATSAPP: string;
  PATIENT_NAME?: string;
  PATIENT_EMAIL?: string;
  CAREGIVER_WHATSAPP?: string;
  CAREGIVER_EMAIL?: string;

  RESEND_API_KEY?: string;
  EMAIL_FROM?: string;
  ACK_SECRET: string;
  PUBLIC_URL: string;
  HEALTHCHECK_URL?: string;
}

export function digits(phone: string | undefined): string {
  return (phone ?? "").replace(/\D/g, "");
}
