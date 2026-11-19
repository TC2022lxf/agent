const sent = new Set<string>()

/** True the first time this boot message is claimed. Survives a StrictMode remount. */
export function claimBoot(key: string): boolean {
  if (sent.has(key)) return false
  sent.add(key)
  return true
}
