import { Select } from 'antd';
import type { PresetTaxonomyFields } from '../api';

export type PresetCategoryItem = PresetTaxonomyFields & {
  category?: string;
};

export function presetCategoryGroup(item: PresetCategoryItem): string {
  return item.category_group || item.category || '其他';
}

export function presetSubcategory(item: PresetCategoryItem): string {
  return item.subcategory || '其他';
}

export function presetCategoryPath(item: PresetCategoryItem): string {
  return `${presetCategoryGroup(item)} / ${presetSubcategory(item)}`;
}

export function sortPresetItems<T extends PresetTaxonomyFields>(items: T[]): T[] {
  return [...items].sort((left, right) => {
    const leftOrder = left.sort_order ?? Number.MAX_SAFE_INTEGER;
    const rightOrder = right.sort_order ?? Number.MAX_SAFE_INTEGER;
    return leftOrder - rightOrder;
  });
}

export function matchesPresetCategory(
  item: PresetCategoryItem,
  categoryGroup: string,
  subcategory: string,
): boolean {
  if (categoryGroup && presetCategoryGroup(item) !== categoryGroup) return false;
  if (subcategory && presetSubcategory(item) !== subcategory) return false;
  return true;
}

export default function PresetCategoryFilter({
  items,
  categoryGroup,
  subcategory,
  onCategoryGroupChange,
  onSubcategoryChange,
  groupWidth = 140,
  subcategoryWidth = 140,
}: {
  items: PresetCategoryItem[];
  categoryGroup: string;
  subcategory: string;
  onCategoryGroupChange: (value: string) => void;
  onSubcategoryChange: (value: string) => void;
  groupWidth?: number;
  subcategoryWidth?: number;
}) {
  const categoryGroups = Array.from(new Set(items.map(presetCategoryGroup)));
  const subcategories = Array.from(
    new Set(
      items
        .filter(
          (item) =>
            !categoryGroup || presetCategoryGroup(item) === categoryGroup,
        )
        .map(presetSubcategory),
    ),
  );

  return (
    <>
      <Select
        allowClear
        placeholder="一级分类"
        style={{ width: groupWidth }}
        value={categoryGroup || undefined}
        options={categoryGroups.map((value) => ({ label: value, value }))}
        onChange={(value) => onCategoryGroupChange(value || '')}
      />
      <Select
        allowClear
        disabled={!categoryGroup}
        placeholder={categoryGroup ? '二级分类' : '先选一级分类'}
        style={{ width: subcategoryWidth }}
        value={subcategory || undefined}
        options={subcategories.map((value) => ({ label: value, value }))}
        onChange={(value) => onSubcategoryChange(value || '')}
      />
    </>
  );
}
