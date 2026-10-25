export function runbookRequestErrorMessage(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })
    .response?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (item && typeof item === 'object' && 'msg' in item) {
          return String((item as { msg?: unknown }).msg || '');
        }
        return String(item || '');
      })
      .filter(Boolean);
    if (messages.length) return messages.join('；');
  }
  if (error instanceof Error && error.message) return error.message;
  return '创建 runbook 失败';
}
