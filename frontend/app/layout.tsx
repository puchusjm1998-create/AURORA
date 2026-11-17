import type { Metadata, Viewport } from "next";
import { Providers } from "@/components/Providers";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "AURORA Logistics AI",
    template: "%s · AURORA Logistics AI",
  },
  description:
    "Plataforma de gestión logística inteligente: inventario en tiempo real, trazabilidad QR, palés, movimientos y auditoría.",
  applicationName: "AURORA Logistics AI",
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    title: "AURORA",
    statusBarStyle: "black-translucent",
  },
  icons: {
    icon: [{ url: "/icon.svg", type: "image/svg+xml" }],
    apple: [{ url: "/icon-192.png", sizes: "192x192" }],
  },
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#05080f",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
