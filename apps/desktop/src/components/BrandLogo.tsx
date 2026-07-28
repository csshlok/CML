type BrandLogoProps = {
  className?: string;
  variant?: "wordmark" | "icon";
  alt?: string;
};

export const VAULT_OPENING_WORDMARK = "/brand/Container.svg";

const brandAssets = {
  wordmark: VAULT_OPENING_WORDMARK,
  icon: "/brand/logo.svg",
} as const;

export function BrandLogo({
  className = "",
  variant = "wordmark",
  alt = "Vault",
}: BrandLogoProps) {
  return (
    <img
      src={brandAssets[variant]}
      alt={alt}
      className={className}
      draggable={false}
    />
  );
}
