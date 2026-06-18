const VARIANTS = {
  primary:
    'bg-accent text-bg hover:bg-[#00be98] disabled:opacity-50 disabled:cursor-not-allowed',
  ghost:
    'bg-transparent text-text-muted hover:text-text-main hover:bg-card-border disabled:opacity-50',
  outline:
    'bg-transparent border border-card-border text-text-main hover:bg-card-border disabled:opacity-50',
}

const SIZES = {
  sm: 'h-8 px-3 text-xs',
  md: 'h-10 px-4 text-sm',
  lg: 'h-12 px-5 text-base',
}

export default function Button({
  variant = 'primary',
  size = 'md',
  className = '',
  type = 'button',
  children,
  ...props
}) {
  return (
    <button
      type={type}
      className={`inline-flex items-center justify-center gap-2 rounded-xl font-semibold
        transition-colors focus:outline-none focus:ring-2 focus:ring-accent/40
        ${VARIANTS[variant] || VARIANTS.primary} ${SIZES[size] || SIZES.md} ${className}`}
      {...props}
    >
      {children}
    </button>
  )
}
