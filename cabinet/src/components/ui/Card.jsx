export function Card({ className = '', children, ...props }) {
  return (
    <div
      className={`rounded-2xl border border-card-border bg-card ${className}`}
      {...props}
    >
      {children}
    </div>
  )
}

export function CardHeader({ className = '', children }) {
  return (
    <div className={`flex items-center justify-between px-5 pt-5 ${className}`}>
      {children}
    </div>
  )
}

export function CardTitle({ className = '', children }) {
  return (
    <h3 className={`text-sm font-semibold text-text-main ${className}`}>
      {children}
    </h3>
  )
}

export function CardContent({ className = '', children }) {
  return <div className={`px-5 py-5 ${className}`}>{children}</div>
}

export default Card
