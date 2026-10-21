"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Material } from "@/lib/types";
import { Badge, Card } from "@/components/ui";
import { MaterialsPanel } from "@/components/goals/MaterialsPanel";

/**
 * 学习目标页的「参考资料 / 例题来源」上传区。
 * 自身负责拉取材料列表，上传/删除成功后由 MaterialsPanel 的 onChanged 重新拉取。
 */
export function GoalMaterialsCard({ goalId }: { goalId: string }) {
  const [materials, setMaterials] = useState<Material[]>([]);

  const load = useCallback(() => {
    api
      .get<Material[]>(`/api/goals/${goalId}/materials`)
      .then(setMaterials)
      .catch(() => setMaterials([]));
  }, [goalId]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <Card
      title="参考资料 / 例题来源"
      desc="上传讲义、教材章节或往年例题：会作为价值诊断、学习计划与教程生成的依据"
      actions={<Badge tone="neutral">{materials.length} 份</Badge>}
    >
      <MaterialsPanel goalId={goalId} materials={materials} onChanged={load} />
    </Card>
  );
}
