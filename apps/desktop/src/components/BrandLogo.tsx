type BrandLogoProps = {
  className?: string;
  variant?: "wordmark" | "icon";
  alt?: string;
};

const brandAssets = {
  wordmark: "/brand/logo.svg",
  icon: "/brand/logo.svg",
} as const;

export function BrandLogo({
  className = "",
  variant = "wordmark",
  alt = "Ponytail",
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
