'use client'

import { motion } from 'framer-motion'

// Fades the wiki in on path change (entering or switching wikis). Templates re-mount
// on path changes but not on ?p= search-param changes, so within-wiki page navigation
// is untouched and keeps KBDetail's own transition.
export default function KBTemplate({ children }: { children: React.ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.2, ease: [0.25, 0.1, 0.25, 1] }}
      className="h-full"
    >
      {children}
    </motion.div>
  )
}
