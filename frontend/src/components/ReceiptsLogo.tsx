/**
 * Receipts mark — a tilted receipt: rectangular body with a zig-zag torn
 * bottom edge and two stub text-lines inside, evoking "proof on paper."
 * One continuous filled path with fill-rule:evenodd cutting the slots and
 * the rule-lines out of the body. Tilt gives it momentum.
 */
export function ReceiptsLogo({ size = 32, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      fill="currentColor"
      aria-label="Receipts"
      role="img"
      className={className}
    >
      <g transform="rotate(-14 50 50)">
        <path
          fillRule="evenodd"
          d="M 22 16 L 78 16 L 78 70 L 74 76 L 68 72 L 62 78 L 56 72 L 50 78 L 44 72 L 38 78 L 32 72 L 26 76 L 22 70 Z M 34 36 L 66 36 L 66 41 L 34 41 Z M 34 50 L 56 50 L 56 55 L 34 55 Z"
        />
      </g>
    </svg>
  );
}
