export default function FieldError({ id, error }: { id?: string; error?: string }) {
  if (!error) return null
  return <p id={id} role="alert" className="mt-1.5 text-xs text-loss-600">{error}</p>
}
