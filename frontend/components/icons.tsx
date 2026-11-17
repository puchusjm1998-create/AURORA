import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

const base = (props: IconProps): IconProps => ({
  xmlns: "http://www.w3.org/2000/svg",
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.7,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  width: 20,
  height: 20,
  "aria-hidden": true,
  ...props,
});

export const IconDashboard = (p: IconProps) => (
  <svg {...base(p)}>
    <rect x="3" y="3" width="7.5" height="7.5" rx="1.6" />
    <rect x="13.5" y="3" width="7.5" height="4.5" rx="1.6" />
    <rect x="13.5" y="10.5" width="7.5" height="10.5" rx="1.6" />
    <rect x="3" y="13.5" width="7.5" height="7.5" rx="1.6" />
  </svg>
);

export const IconScan = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M4 8V5.5A1.5 1.5 0 0 1 5.5 4H8" />
    <path d="M16 4h2.5A1.5 1.5 0 0 1 20 5.5V8" />
    <path d="M20 16v2.5a1.5 1.5 0 0 1-1.5 1.5H16" />
    <path d="M8 20H5.5A1.5 1.5 0 0 1 4 18.5V16" />
    <path d="M3.5 12h17" />
  </svg>
);

export const IconBox = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Z" />
    <path d="m4.3 7.7 7.7 4.4 7.7-4.4" />
    <path d="M12 12.1V21" />
  </svg>
);

export const IconPallet = (p: IconProps) => (
  <svg {...base(p)}>
    <rect x="3.5" y="4" width="7" height="7" rx="1" />
    <rect x="13" y="4" width="7" height="7" rx="1" />
    <path d="M3 15h18" />
    <path d="M5 15v3.5M12 15v3.5M19 15v3.5" />
    <path d="M3 19h18" />
  </svg>
);

export const IconWarehouse = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M3 21V9.5L12 4l9 5.5V21" />
    <path d="M7 21v-7h10v7" />
    <path d="M7 17.5h10" />
    <path d="M10.5 14v7M13.5 14v7" />
  </svg>
);

export const IconMovements = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M4 8h13l-3-3" />
    <path d="M20 16H7l3 3" />
  </svg>
);

export const IconInvoice = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M6 3h9l4 4v14a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z" />
    <path d="M14.5 3v4.5H19" />
    <path d="M8.5 12h7M8.5 15.5h5M8.5 8.5h2" />
  </svg>
);

export const IconReports = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M4 20V4" />
    <path d="M4 20h16" />
    <rect x="7.5" y="12" width="3" height="5" rx="0.8" />
    <rect x="13" y="8" width="3" height="9" rx="0.8" />
    <rect x="18" y="5" width="2.5" height="12" rx="0.8" />
  </svg>
);

export const IconUsers = (p: IconProps) => (
  <svg {...base(p)}>
    <circle cx="9" cy="8" r="3.4" />
    <path d="M3 20c0-3.2 2.7-5.3 6-5.3s6 2.1 6 5.3" />
    <path d="M16 5.2a3.4 3.4 0 0 1 0 6.5" />
    <path d="M18 14.9c2 .7 3.3 2.3 3.3 4.5" />
  </svg>
);

export const IconShield = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M12 3 5 6v5.5c0 4.5 3 7.9 7 9.5 4-1.6 7-5 7-9.5V6l-7-3Z" />
    <path d="m9 12 2.2 2.2L15.5 10" />
  </svg>
);

export const IconSearch = (p: IconProps) => (
  <svg {...base(p)}>
    <circle cx="11" cy="11" r="6.5" />
    <path d="m16 16 4.5 4.5" />
  </svg>
);

export const IconPlus = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M12 5v14M5 12h14" />
  </svg>
);

export const IconClose = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="m6 6 12 12M18 6 6 18" />
  </svg>
);

export const IconCheck = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="m5 12.5 4.5 4.5L19 7" />
  </svg>
);

export const IconAlert = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M12 4 2.8 20h18.4L12 4Z" />
    <path d="M12 9.5v4.5M12 17.2v.1" />
  </svg>
);

export const IconRoute = (p: IconProps) => (
  <svg {...base(p)}>
    <circle cx="5" cy="18" r="2.2" />
    <circle cx="19" cy="6" r="2.2" />
    <path d="M7.2 18h6.3a3.5 3.5 0 0 0 0-7H10a3.5 3.5 0 0 1 0-7h6.8" />
  </svg>
);

export const IconClock = (p: IconProps) => (
  <svg {...base(p)}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3.2 2" />
  </svg>
);

export const IconIncident = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M12 3.5 2.6 20h18.8L12 3.5Z" />
    <path d="M12 9v5" />
    <path d="M12 17.3v.2" />
  </svg>
);

export const IconPrint = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M7 8V4h10v4" />
    <rect x="4" y="8" width="16" height="8" rx="1.6" />
    <path d="M7 13h10v7H7z" />
  </svg>
);

export const IconDownload = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M12 4v11" />
    <path d="m7.5 11 4.5 4.5 4.5-4.5" />
    <path d="M4.5 20h15" />
  </svg>
);

export const IconRefresh = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M20 11a8 8 0 1 0-2.4 6.3" />
    <path d="M20 5v6h-6" />
  </svg>
);

export const IconCamera = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M4 8h3l1.5-2h7L17 8h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1Z" />
    <circle cx="12" cy="13" r="3.4" />
  </svg>
);

export const IconArrowIn = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M12 4v12" />
    <path d="m7 11 5 5 5-5" />
    <path d="M4 20h16" />
  </svg>
);

export const IconArrowOut = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M12 20V8" />
    <path d="m7 13 5-5 5 5" />
    <path d="M4 4h16" />
  </svg>
);

export const IconMenu = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M4 7h16M4 12h16M4 17h16" />
  </svg>
);

export const IconLogout = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M15 4h3a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-3" />
    <path d="M10 8l-4 4 4 4" />
    <path d="M6 12h9" />
  </svg>
);

export const IconQr = (p: IconProps) => (
  <svg {...base(p)}>
    <rect x="3.5" y="3.5" width="6.5" height="6.5" rx="1" />
    <rect x="14" y="3.5" width="6.5" height="6.5" rx="1" />
    <rect x="3.5" y="14" width="6.5" height="6.5" rx="1" />
    <path d="M14 14h2.5v2.5H14zM18 18h2.5v2.5H18zM14 20.5h1.5M20.5 14v1.5" />
  </svg>
);

export const IconMic = (p: IconProps) => (
  <svg {...base(p)}>
    <rect x="9" y="3" width="6" height="10" rx="3" />
    <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0" />
    <path d="M12 18v3.5M9 21.5h6" />
  </svg>
);

export const IconInfo = (p: IconProps) => (
  <svg {...base(p)}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 11v5.5M12 7.7v.1" />
  </svg>
);

export const IconTrash = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M4 7h16" />
    <path d="M9 7V4.5h6V7" />
    <path d="M6 7l1 13h10l1-13" />
    <path d="M10 11v5M14 11v5" />
  </svg>
);

export const IconChevron = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="m9 6 6 6-6 6" />
  </svg>
);

export const IconLock = (p: IconProps) => (
  <svg {...base(p)}>
    <rect x="4.5" y="10" width="15" height="10" rx="2" />
    <path d="M8 10V7.5a4 4 0 0 1 8 0V10" />
    <path d="M12 14v2.5" />
  </svg>
);

export const IconKey = (p: IconProps) => (
  <svg {...base(p)}>
    <circle cx="8" cy="12" r="3.2" />
    <path d="M11.2 12H20" />
    <path d="M17 12v3.2" />
    <path d="M20 12v2.2" />
  </svg>
);

export const IconTask = (p: IconProps) => (
  <svg {...base(p)}>
    <rect x="5" y="4" width="14" height="17" rx="2" />
    <path d="M9 4.5V3h6v1.5" />
    <path d="M8.5 10h7" />
    <path d="M8.5 13.5h7" />
    <path d="M8.5 17h4" />
  </svg>
);

export const IconReserve = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M7 4h10a1 1 0 0 1 1 1v15l-6-4-6 4V5a1 1 0 0 1 1-1Z" />
  </svg>
);

export const IconActivity = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M3 12h4l2.5-7 4 14 2.5-7h5" />
  </svg>
);

export const IconPin = (p: IconProps) => (
  <svg {...base(p)}>
    <path d="M12 21s-6.5-5.5-6.5-11a6.5 6.5 0 0 1 13 0C18.5 15.5 12 21 12 21Z" />
    <circle cx="12" cy="10" r="2.4" />
  </svg>
);
