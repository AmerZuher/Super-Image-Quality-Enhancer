"use client"

import { useEffect, useRef, useState, Suspense } from "react" // Import Suspense
import styles from "./compare.module.css"
import "../globals.css";
import Image from "next/image"
import { useSearchParams } from "next/navigation"

// Your original Compare component
const Compare = () => {
  const [originalImage, setOriginalImage] = useState<string | null>(null)
  const [enhancedImage, setEnhancedImage] = useState<string | null>(null)
  const [clipPathValue, setClipPathValue] = useState<string>("inset(0 50% 0 0)")

  const imageCompareRef = useRef<HTMLDivElement>(null)
  const sliderRef = useRef<HTMLDivElement>(null)
  const image2Ref = useRef<HTMLDivElement>(null)

  const isClicked = useRef<boolean>(false)
  const mPos = useRef<{ x: number; y: number }>({ x: 0, y: 0 })

  // useSearchParams is used here
  const searchParams = useSearchParams()

  // Get image URLs directly from URL parameters
  const originalUrl = searchParams.get("originalUrl")
  const enhancedUrl = searchParams.get("enhancedUrl")

  useEffect(() => {
    // Set images directly from URL parameters
    if (originalUrl) {
      setOriginalImage(decodeURIComponent(originalUrl))
    }

    if (enhancedUrl) {
      setEnhancedImage(decodeURIComponent(enhancedUrl))
    }
  }, [originalUrl, enhancedUrl])

  useEffect(() => {
    const compareEl = imageCompareRef.current
    const sliderEl = sliderRef.current
    const image2El = image2Ref.current

    if (!compareEl || !sliderEl || !image2El) return

    image2El.style.clipPath = clipPathValue
    image2El.style.setProperty("-webkit-clip-path", clipPathValue)

    const handleMouseDown = () => (isClicked.current = true)
    const handleMouseUp = () => (isClicked.current = false)
    const handleMouseMove = (e: MouseEvent) => {
      mPos.current.x = e.clientX
      mPos.current.y = e.clientY
    }

    compareEl.addEventListener("mousedown", handleMouseDown)
    compareEl.addEventListener("mouseup", handleMouseUp)
    compareEl.addEventListener("mousemove", handleMouseMove)

    const update = () => {
      requestAnimationFrame(update)
      if (isClicked.current && compareEl && sliderEl && image2El) {
        const rect = compareEl.getBoundingClientRect()
        if (mPos.current.x > rect.x && mPos.current.x < rect.x + rect.width) {
          const newClipValue = `inset(0 ${100 - ((mPos.current.x - rect.x) / rect.width) * 100}% 0 0)`
          image2El.style.clipPath = newClipValue
          image2El.style.setProperty("-webkit-clip-path", newClipValue)
          sliderEl.style.left = `${mPos.current.x - rect.x}px`
        }
      }
    }
    update()

    return () => {
      compareEl.removeEventListener("mousedown", handleMouseDown)
      compareEl.removeEventListener("mouseup", handleMouseUp)
      compareEl.removeEventListener("mousemove", handleMouseMove)
    }
  }, [clipPathValue])

  return (
    <main className={styles.app}>
      <span className={styles.labels}>Original</span>
      <section className={styles.imageCompare} ref={imageCompareRef}>
        <div className={styles.image1}>
          <Image
            src={enhancedImage || "/Icons/None.png"}
            alt="Enhanced Image"
            layout="fill"
            objectFit="cover"
            priority
            unoptimized={!!enhancedImage} // Use unoptimized for external URLs
          />
        </div>
        <div className={styles.image2} ref={image2Ref} style={{ clipPath: clipPathValue }}>
          <Image
            src={originalImage || "/Icons/None.png"}
            alt="Original Image"
            layout="fill"
            objectFit="cover"
            priority
            unoptimized={!!originalImage} // Use unoptimized for external URLs
          />
        </div>
        <div className={styles.slider} ref={sliderRef}>
          <button className={styles.cirlce}>
            <svg viewBox="0 0 24 24">
              <path fill="#fff" d="M15.41,16.58L10.83,12L15.41,7.41L14,6L8,12L14,18L15.41,16.58Z" />
            </svg>
            <svg viewBox="0 0 24 24">
              <path fill="#fff" d="M8.59,16.58L13.17,12L8.59,7.41L10,6L16,12L10,18L8.59,16.58Z" />
            </svg>
          </button>
        </div>
      </section>
      <span className={styles.labels}>Enhanced</span>
    </main>
  )
}

// Export a wrapper component that includes Suspense
export default function ComparePageWithSuspense() {
  return (
    // Wrap the Compare component with Suspense
    <Suspense fallback={<div>Loading...</div>}> {/* Provide a fallback UI */}
      <Compare />
    </Suspense>
  );
}
