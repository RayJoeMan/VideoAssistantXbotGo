/**
 * Structured logging for the module backend.
 *
 * Every important operation logs enough context to troubleshoot failures:
 * timestamp, environment, module, version, tenant ID, operation,
 * correlation/request ID, severity. Never log passwords, tokens, payment
 * information, or unnecessary PII.
 *
 * Callers supply `operation` (required) plus optional tenant/uid/correlation
 * context; module identity, version, environment, and timestamp are added
 * automatically.
 */
export interface LogContext {
  operation: string
  tenantId?: string
  uid?: string
  correlationId?: string
  [key: string]: unknown
}

const MODULE_ID = 'aeiv-sponsors'
const MODULE_VERSION = '0.1.0'
const ENVIRONMENT = process.env.FUNCTIONS_EMULATOR ? 'emulator' : 'production'

function buildEntry(context: LogContext, severity: string, message: string, extra?: unknown) {
  const entry: Record<string, unknown> = {
    timestamp: new Date().toISOString(),
    severity,
    message,
    module: MODULE_ID,
    version: MODULE_VERSION,
    environment: ENVIRONMENT,
    ...context,
  }
  if (extra !== undefined) {
    // extra is expected to be sanitized by callers; no PII should be included.
    entry.details = extra
  }
  return entry
}

export function logInfo(context: LogContext, message: string, extra?: unknown): void {
  console.log(JSON.stringify(buildEntry(context, 'INFO', message, extra)))
}

export function logWarn(context: LogContext, message: string, extra?: unknown): void {
  console.warn(JSON.stringify(buildEntry(context, 'WARN', message, extra)))
}

export function logError(context: LogContext, message: string, error?: unknown): void {
  const detail = error instanceof Error ? { name: error.name, message: error.message } : error
  console.error(JSON.stringify(buildEntry(context, 'ERROR', message, detail)))
}
