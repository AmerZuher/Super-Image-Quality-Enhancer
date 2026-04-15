"use client";

import { useState, useEffect, useRef } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import type React from "react"; // Import React type if needed for event handlers

// Renamed component for clarity, you can keep 'Home' if it's the main page export
const ImageEnhancerUI = () => {
  const router = useRouter();

  // State from the 'Home' component (dynamic functionality)
  const [file, setFile] = useState<File | null>(null);
  const [imageId, setImageId] = useState<string | null>(null);
  const [enhancedImage, setEnhancedImage] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [originalImageUrl, setOriginalImageUrl] = useState<string | null>(null); // New state for original image URL

  const [isLoading, setIsLoading] = useState(false); // Loading state for upload/enhance
  const [isEnhancing, setIsEnhancing] = useState(false); // Specific state for enhancement step

  // State from the 'Body' component (layout requirements)
  const [fileName, setFileName] = useState<string>("No Selected Image");
  const [processingTime, setProcessingTime] = useState<number | null>(null); // Placeholder - Needs API data
  const [originalResolution, setOriginalResolution] = useState<string | null>(null); // Placeholder - Needs API data
  const [enhancedResolution, setEnhancedResolution] = useState<string | null>(null); // Placeholder - Needs API data

  // Refs from 'Body' component
  const fileInputRef = useRef<HTMLInputElement>(null);
  const processedImageRef = useRef<HTMLImageElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const selectedFile = e.target.files[0];
      setFile(selectedFile);
      setFileName(selectedFile.name); // Update file name display

      // Create local preview
      const objectUrl = URL.createObjectURL(selectedFile);
      setPreview(objectUrl); // Show local preview immediately

      // Reset states for new file
      setEnhancedImage(null);
      setImageId(null);
      setOriginalImageUrl(null); // Reset original image URL as well
      // Reset potential status info if needed
      setProcessingTime(null);
      setOriginalResolution(null);
      setEnhancedResolution(null);
    }
  };

  const handleUpload = async () => {
    if (!file) return;
    setIsLoading(true);
    setEnhancedImage(null); // Clear previous enhanced image if re-uploading
    setOriginalImageUrl(null); // Clear previous original image URL

    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch("http://localhost:8000/upload/", { // Use the backend service name
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        throw new Error(`Failed to upload image: ${response.statusText}`);
      }

      const data = await response.json();
      setImageId(data.id);
      // Construct the full URL for the original image using the backend service name
      setOriginalImageUrl(`http://localhost:8000${data.original_url}`);
    } catch (error) {
      console.error("Error uploading image:", error);
      alert(`Failed to upload image. ${error instanceof Error ? error.message : String(error)}`);
      setFile(null); // Reset file state on error?
      setFileName("No Selected Image");
      setPreview(null);
      setOriginalImageUrl(null);
    } finally {
      setIsLoading(false);
    }
  };

  const handleEnhance = async () => {
    if (!imageId) return;

    setIsEnhancing(true);
    setIsLoading(true); // Use general loading state for button disabling
    const startTime = performance.now();

    try {
      const response = await fetch(`http://localhost:8000/enhance/${imageId}`, { // Use the backend service name
        method: "POST",
      });

      if (!response.ok) {
        throw new Error(`Failed to enhance image: ${response.statusText}`);
      }

      const data = await response.json();
      const endTime = performance.now();
      // Construct the full URL for the enhanced image using the backend service name
      setEnhancedImage(`http://localhost:8000${data.enhanced_url}`);
      setProcessingTime(Math.round((endTime - startTime) / 1000)); // Calculate rough processing time client-side
    } catch (error) {
      console.error("Error enhancing image:", error);
      alert(`Failed to enhance image. ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setIsEnhancing(false);
      setIsLoading(false);
    }
  };

  const handleCompareClick = () => {
    if (originalImageUrl && enhancedImage) {
      // This is where the data is correctly passed to the compare page via URL params
      router.push(`/compare?originalUrl=${encodeURIComponent(originalImageUrl)}&enhancedUrl=${encodeURIComponent(enhancedImage)}`);
    } else {
      alert("Please upload and enhance an image before comparing.");
    }
  };


  const toggleFullScreen = (element: HTMLElement) => {
    if (!document.fullscreenElement) {
      element
        .requestFullscreen()
        .catch((err) => console.error(`Error attempting to enable full-screen mode: ${err.message}`));
    } else {
      document.exitFullscreen();
    }
  };

  const handleDownloadClick = async () => {
    if (!enhancedImage) {
      alert("No enhanced image to download.");
      return;
    }

    try {
      setIsLoading(true); // Show loading state during download fetch
      const response = await fetch(enhancedImage); // Fetch the image from the backend
      if (!response.ok) {
        throw new Error(`Failed to fetch enhanced image: ${response.statusText}`)
      }
      const blob = await response.blob();

      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      const baseName = fileName.includes('.') ? fileName.substring(0, fileName.lastIndexOf('.')) : fileName;
      const extension = fileName.includes('.') ? fileName.substring(fileName.lastIndexOf('.')) : '.png'; // Assuming enhanced is png
      link.download = `enhanced_${baseName}${extension}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(link.href); // Clean up blob URL
    } catch (error) {
      console.error("Error downloading image:", error);
      alert(`Failed to download image. ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setIsLoading(false);
    }
  };

  const handleStartClick = () => {
    if (!file) {
      alert("Please select an image first.");
      return;
    }
    // If file is selected but not uploaded (no imageId yet), upload it
    if (!imageId) {
      handleUpload();
    }
    // If file is uploaded (imageId exists) but not enhanced, enhance it
    else if (!enhancedImage) {
      handleEnhance();
    }
    // If already uploaded and enhanced
    else {
      alert("Image already enhanced. You can compare or download.");
    }
  };

  // REMOVED THE PROBLEMATIC useEffect HERE

  useEffect(() => {
    let currentPreview = preview;
    return () => {
      if (currentPreview && currentPreview.startsWith("blob:")) {
        URL.revokeObjectURL(currentPreview);
      }
    };
  }, [preview]);

  return (
    <main className="app-content">
      {/* Projects Section - Image Preview Area */}
      <section className="preview-area">
        <div className="projects-status">
          {/* Status Info - Populated if API provides data */}
          <div className="left-text">
            <p id="enhanced-resolution">
              {enhancedResolution ? `Enhanced Resolution: ${enhancedResolution}` : enhancedImage ? '' : ''}
            </p>
          </div>
          <div>
            <p id="processing-time">
              {processingTime !== null ? `Processing Time: ${processingTime} seconds` : ''}
            </p>
          </div>
          <div className="right-text">
            <p id="original-resolution">
              {originalResolution ? `Original Resolution: ${originalResolution}` : file ? '' : ''}
            </p>
          </div>
        </div>
        <div className="image-preview-container">
          <Image
            src={enhancedImage || preview || "/Icons/None.png"}
            alt={enhancedImage ? "Enhanced Image" : preview ? "Image Preview" : "No image selected"}
            fill
            style={{ objectFit: 'contain' }}
            id="processedImage"
            ref={processedImageRef}
            priority={!!(enhancedImage || preview)}
            unoptimized={enhancedImage?.startsWith('http') || preview?.startsWith('http')}
            onClick={() =>
              (enhancedImage || preview) && processedImageRef.current && toggleFullScreen(processedImageRef.current)
            }
            title="Toggle Fullscreen"
          />
        </div>

      </section>

      {/* Settings Section - Controls */}
      <aside className="controls-section">

        <div className="container"> {/* Keep class name if CSS depends on it */}
          <div className="conotrols">
            {/* Hidden file input */}
            <input
              type="file"
              id="file-input"
              accept="image/*"
              className="input_button" // Keep class if styled
              style={{ display: "none" }}
              ref={fileInputRef}
              onChange={handleFileChange}
              disabled={isLoading} // Disable when loading
            />
            {/* Label acts as the visible button */}
            <label htmlFor="file-input" className={`start_button  ${isLoading ? 'button-disabled' : ''}`}>
              Select Image
            </label>
          </div>
          {/* Display selected file name */}
        </div>

        {/* Action Buttons Container */}
        <div className="conotrols">
          {/* Using original "Start" button, but text/action changes */}
          <button
            type="button"
            id="startButton"
            className={`action_buttons ${(!file || enhancedImage || isLoading) ? 'button-disabled' : ''}`}
            onClick={handleStartClick}
            disabled={!file || !!enhancedImage || isLoading} // Disable if no file, or already enhanced, or loading
          >
            {isLoading ? (isEnhancing ? "Enhancing..." : "Uploading...") : !imageId ? "Upload" : "Enhance"}
          </button>
        </div>

        <div className="conotrols">
          {/* Download Button */}
          <button
            type="button"
            className={`action_buttons ${!enhancedImage || isLoading ? 'button-disabled' : ''}`}
            onClick={handleDownloadClick}
            disabled={!enhancedImage || isLoading} // Enable only when enhanced image exists and not loading
          >
            Download
          </button>
          {/* Compare Button */}
          <button
            type="button"
            className={`action_buttons ${!enhancedImage || !originalImageUrl || isLoading ? 'button-disabled' : ''}`}
            onClick={handleCompareClick}
            disabled={!enhancedImage || !originalImageUrl || isLoading} // Enable only when both enhanced and original image URLs exist and not loading
          >
            Compare
          </button>
        </div>
      </aside>
    </main>
  );
};

export default ImageEnhancerUI;
