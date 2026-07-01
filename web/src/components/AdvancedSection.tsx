import type { ReactNode } from "react";

interface AdvancedSectionProps {
  children: ReactNode;
  enabled: boolean;
}

export function AdvancedSection({ children, enabled }: AdvancedSectionProps) {
  if (!enabled) {
    return null;
  }
  return <>{children}</>;
}
