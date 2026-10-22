import { motion, AnimatePresence } from 'framer-motion'
import { Upload as UploadIcon } from 'lucide-react'

export function FileDropOverlay({ isVisible }: { isVisible: boolean }) {
  return (
    <AnimatePresence>
      {isVisible && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          className="absolute inset-0 z-50 bg-background/80 backdrop-blur-sm flex items-center justify-center pointer-events-none"
        >
          <div className="flex flex-col items-center gap-3 border-2 border-dashed border-primary rounded-xl px-12 py-10">
            <UploadIcon className="size-8 text-primary" />
            <p className="text-sm font-medium text-primary">Drop files to upload</p>
            <p className="text-xs text-muted-foreground">PDF, Word, PowerPoint, images, and more</p>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
