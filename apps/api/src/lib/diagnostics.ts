type AuthDiagnostic =
  | { readonly event: "auth.code.suppressed"; readonly reason: "email" | "ip" | "device" | "configuration" }
  | { readonly event: "auth.provider.failed"; readonly errorType: string }
  | { readonly event: "auth.session.created" }
  | { readonly event: "auth.session.expired" }
  | { readonly event: "auth.session.revoked" };

type NewsletterDiagnostic =
  | { readonly event: "newsletter.issue.created"; readonly issueId: string }
  | { readonly event: "newsletter.issue.reused"; readonly issueId: string }
  | { readonly event: "newsletter.delivery.claimed"; readonly issueId: string; readonly attempt: number }
  | { readonly event: "newsletter.delivery.retry"; readonly issueId: string; readonly attempt: number }
  | { readonly event: "newsletter.delivery.failed"; readonly issueId: string; readonly attempt: number }
  | { readonly event: "newsletter.delivery.cancelled"; readonly issueId: string }
  | { readonly event: "newsletter.batch.completed"; readonly processed: number; readonly sent: number };

type AiDiagnostic =
  | { readonly event: "ai.explain.failed"; readonly errorType: string }
  | { readonly event: "ai.termask.failed"; readonly errorType: string };

export type DiagnosticEvent = AuthDiagnostic | NewsletterDiagnostic | AiDiagnostic;

export function diagnosticInfo(event: DiagnosticEvent): void {
  console.info(JSON.stringify(event));
}

export function diagnosticWarn(event: DiagnosticEvent): void {
  console.warn(JSON.stringify(event));
}

export function diagnosticError(event: DiagnosticEvent): void {
  console.error(JSON.stringify(event));
}

export function errorType(error: unknown): string {
  return error instanceof Error ? error.name : "UnknownError";
}
