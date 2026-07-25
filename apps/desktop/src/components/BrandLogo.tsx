type BrandLogoProps = {
  className?: string;
  variant?: "wordmark" | "icon";
  alt?: string;
};

const brandAssets = {
  wordmark: "/brand/Container.svg",
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
