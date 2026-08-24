// 数据看板状态：类型、日期筛选、分页、导出
import useStore from 'resso';
import { api, type RecordsResult } from '../api';

export type RecordsKind = 'agent' | 'draw' | 'prompt';

interface RecordsState {
  kind: RecordsKind;
  page: number;
  pageSize: number;
  dateFrom: string;
  dateTo: string;
  data: RecordsResult | null;
  loading: boolean;
  [key: string]: unknown;
}

export const recordsStore = useStore<RecordsState>({
  kind: 'agent',
  page: 1,
  pageSize: 10,
  dateFrom: '',
  dateTo: '',
  data: null,
  loading: false,
});

// 请求记录列表
export async function loadRecords(): Promise<void> {
  recordsStore.loading = true;
  try {
    const { data } = await api.get<RecordsResult>('/records', {
      params: {
        kind: recordsStore.kind,
        page: recordsStore.page,
        page_size: recordsStore.pageSize,
        date_from: recordsStore.dateFrom || undefined,
        date_to: recordsStore.dateTo || undefined,
      },
    });
    recordsStore.data = data;
  } catch (e) {
    recordsStore.data = null;
  } finally {
    recordsStore.loading = false;
  }
}

// 导出当前筛选范围的 Excel
export function exportExcel(): void {
  const params = new URLSearchParams();
  if (recordsStore.dateFrom) params.set('date_from', recordsStore.dateFrom);
  if (recordsStore.dateTo) params.set('date_to', recordsStore.dateTo);
  window.open(`/api/export/${recordsStore.kind}?${params.toString()}`, '_blank');
}
