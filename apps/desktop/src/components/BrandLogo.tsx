type BrandLogoProps = {
  className?: string;
  variant?: "wordmark" | "icon";
  alt?: string;
};

const brandAssets = {
  wordmark: "/brand/vault-logo.png",
  icon: "/brand/vault-icon.png",
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

