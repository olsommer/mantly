interface TenantBranding {
  primaryColor?: string | null;
}

const DEFAULT_THEME = {
  primary: "oklch(0.205 0 0)",
  primaryForeground: "oklch(0.985 0 0)",
  ring: "oklch(0.708 0 0)",
};

const HEX_COLOR_RE = /^#[0-9A-Fa-f]{6}$/;

function foregroundForHex(hex: string): string {
  const r = Number.parseInt(hex.slice(1, 3), 16) / 255;
  const g = Number.parseInt(hex.slice(3, 5), 16) / 255;
  const b = Number.parseInt(hex.slice(5, 7), 16) / 255;
  const linear = [r, g, b].map((channel) => {
    if (channel <= 0.03928) return channel / 12.92;
    return ((channel + 0.055) / 1.055) ** 2.4;
  });
  const luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
  return luminance > 0.52 ? "#111111" : "#FFFFFF";
}

export function applyTenantBranding(branding?: TenantBranding | null) {
  const root = document.documentElement;
  const primary = (branding?.primaryColor ?? "").trim();

  if (!HEX_COLOR_RE.test(primary)) {
    root.style.setProperty("--primary", DEFAULT_THEME.primary);
    root.style.setProperty("--primary-foreground", DEFAULT_THEME.primaryForeground);
    root.style.setProperty("--ring", DEFAULT_THEME.ring);
    return;
  }

  const color = primary.toUpperCase();
  root.style.setProperty("--primary", color);
  root.style.setProperty("--primary-foreground", foregroundForHex(color));
  root.style.setProperty("--ring", color);
}
