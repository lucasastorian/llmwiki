import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

const FILENAME_BAD_CHARS = /[/\\:*?"<>|]/g

export function sanitizeTitle(title: string): string {
  return title.replace(FILENAME_BAD_CHARS, '')
}

export function toDisplayTitle(title: string): string {
  if (title !== title.toLowerCase()) return title
  return title.replace(/\b\w/g, (c) => c.toUpperCase())
}
