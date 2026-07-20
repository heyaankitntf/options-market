/**
 * Credential encryption helpers (AES-256-GCM).
 * Used to store portal passwords at rest.
 */

import crypto from 'crypto'

const ALGO = 'aes-256-gcm'
// In production this would come from a KMS / env var. Derive a stable key.
const SECRET =
  process.env.OPTFLOW_SECRET ||
  'optflow-dev-secret-change-in-production-32b!'

function getKey(): Buffer {
  return crypto.createHash('sha256').update(SECRET).digest()
}

export interface EncryptedBlob {
  cipher: string
  iv: string
  tag: string
}

export function encrypt(plain: string): EncryptedBlob {
  const iv = crypto.randomBytes(12)
  const cipher = crypto.createCipheriv(ALGO, getKey(), iv)
  const enc = Buffer.concat([cipher.update(plain, 'utf8'), cipher.final()])
  const tag = cipher.getAuthTag()
  return { cipher: enc.toString('base64'), iv: iv.toString('base64'), tag: tag.toString('base64') }
}

export function decrypt(blob: EncryptedBlob): string {
  const decipher = crypto.createDecipheriv(ALGO, getKey(), Buffer.from(blob.iv, 'base64'))
  decipher.setAuthTag(Buffer.from(blob.tag, 'base64'))
  const dec = Buffer.concat([decipher.update(Buffer.from(blob.cipher, 'base64')), decipher.final()])
  return dec.toString('utf8')
}

/** Mask a string for display, e.g. "mySecret" -> "my*****t". */
export function maskSecret(s: string): string {
  if (s.length <= 4) return '****'
  return s.slice(0, 2) + '*'.repeat(Math.max(4, s.length - 4)) + s.slice(-2)
}
