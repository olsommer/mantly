function envOrFallback(value: string | undefined, fallback: string) {
  const trimmed = value?.trim();
  return trimmed ? trimmed : fallback;
}

export const POSTHOG_TOKEN =
  envOrFallback(
    import.meta.env.VITE_PUBLIC_POSTHOG_TOKEN as string | undefined,
    "phc_eT3ok7puggPssO9jOV8WsuELjznLPZiZYUAFli5goRm"
  );

export const POSTHOG_HOST =
  envOrFallback(
    import.meta.env.VITE_PUBLIC_POSTHOG_HOST as string | undefined,
    "https://eu.i.posthog.com"
  );
