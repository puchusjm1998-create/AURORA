"use client";

import { PageHeader } from "@/components/ui";
import { AlertsPanel } from "@/components/AlertsPanel";

export default function AlertsPage() {
  return (
    <>
      <PageHeader
        eyebrow="Control operativo"
        title="Alertas"
        subtitle="Reglas sobre indicadores reales, con reconocimiento, resolución y aviso por correo."
      />
      <AlertsPanel />
    </>
  );
}
