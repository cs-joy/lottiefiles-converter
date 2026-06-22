"use client";

import { useState, useRef, useEffect } from "react";
import dynamic from "next/dynamic";

// Dynamically import the named export 'Player', and explicitly disable SSR
const Player = dynamic(
  () => import("@lottiefiles/react-lottie-player").then((mod) => mod.Player),
  { ssr: false }
)

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<"IDLE" | "UPLOADING" | "PROCESSING" | "COMPLETED" | "FAILED">("IDLE");
  const [jobId, setJobId] = useState<string | null>(null);
  const [lottieUrl, setLottieUrl] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [lottieData, setLottieData] = useState<any>(null); // Holds the actual JSON object
  
  // Notice we use port 8001 based on our docker-compose host mapping
  const API_BASE = "https://saddling-reunion-riveting.ngrok-free.dev";

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setFile(e.target.files[0]);
      setStatus("IDLE");
      setLottieUrl(null);
      setErrorMsg(null);
    }
  };

  const handleUpload = async () => {
    if (!file) return;
    setStatus("UPLOADING");
    setErrorMsg(null);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch(`${API_BASE}/convert/`, {
        method: "POST",
        body: formData,
        headers: {
          "ngrok-skip-browser-warning": "true" // Tells ngrok to skip the HTML warning page
        }
      });

      if (!response.ok) throw new Error("Upload failed");

      const data = await response.json();
      setJobId(data.job_id);
      setStatus("PROCESSING");
    } catch (err: any) {
      setErrorMsg(err.message || "An error occurred during upload.");
      setStatus("FAILED");
    }
  };

  // Polling logic to check job status
  useEffect(() => {
    let interval: NodeJS.Timeout;

    const checkStatus = async () => {
      if (!jobId || status !== "PROCESSING") return;

      try {
        const response = await fetch(`${API_BASE}/status/${jobId}`, {
          headers: {
            "ngrok-skip-browser-warning": "true" // Tells ngrok to skip the HTML warning page
          }
        });
        const data = await response.json();

        if (data.status === "COMPLETED") {
          const fileName = data.output_url.split("/").pop();
          const fileUrl = `${API_BASE}/outputs/${fileName}`;
          
          // 1. Fetch the file manually to bypass ngrok
          try {
            const fileResponse = await fetch(fileUrl, {
              headers: {
                "ngrok-skip-browser-warning": "true"
              }
            });
            
            // 2. Parse the JSON and save it to state
            const animationData = await fileResponse.json();
            setLottieData(animationData);
            
          } catch (err) {
            console.error("Failed to load Lottie JSON", err);
          }

          setLottieUrl(fileUrl);
          setStatus("COMPLETED");
        }
      } catch (err) {
        console.error("Error checking status", err);
      }
    };

    if (status === "PROCESSING") {
      interval = setInterval(checkStatus, 2000); // Poll every 2 seconds
    }

    return () => clearInterval(interval);
  }, [jobId, status]);

  return (
    <main className="min-h-screen bg-gray-50 flex flex-col items-center py-20 px-4 text-gray-900">
      <div className="w-full max-w-2xl bg-white rounded-xl shadow-xl p-8">
        <h1 className="text-3xl font-bold mb-2 text-center">Video to Lottie Converter</h1>
        <p className="text-gray-500 text-center mb-8">Upload a short video (under 1.6MB target limit)</p>

        {/* Upload Section */}
        <div className="border-2 border-dashed border-gray-300 rounded-lg p-10 flex flex-col items-center justify-center mb-6 bg-gray-50 hover:bg-gray-100 transition">
          <input 
            type="file" 
            accept="video/*" 
            onChange={handleFileChange} 
            className="mb-4 text-sm text-gray-600 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
          />
          <button
            onClick={handleUpload}
            disabled={!file || status === "UPLOADING" || status === "PROCESSING"}
            className="bg-blue-600 text-white px-6 py-2 rounded-lg font-medium disabled:opacity-50 disabled:cursor-not-allowed hover:bg-blue-700 transition"
          >
            {status === "UPLOADING" ? "Uploading..." : "Convert to Lottie"}
          </button>
        </div>

        {/* Status Indicators */}
        {status === "PROCESSING" && (
          <div className="text-center p-6 bg-blue-50 rounded-lg border border-blue-100">
            <div className="animate-spin h-8 w-8 border-4 border-blue-600 border-t-transparent rounded-full mx-auto mb-4"></div>
            <p className="text-blue-800 font-medium">Processing your video...</p>
            <p className="text-sm text-blue-600 mt-1">Extracting frames and compressing to WebP vectors.</p>
          </div>
        )}

        {status === "FAILED" && (
          <div className="text-center p-6 bg-red-50 rounded-lg border border-red-100 text-red-700">
            <p className="font-bold">Error</p>
            <p>{errorMsg}</p>
          </div>
        )}

        {/* Success / Player Section */}
        {status === "COMPLETED" && lottieData && ( // Check for lottieData here
          <div className="mt-8 border-t pt-8">
            <h2 className="text-xl font-bold mb-4 text-center text-green-600">Conversion Successful!</h2>
            
            <div className="bg-gray-100 rounded-lg p-4 mb-6 flex justify-center">
              <Player
                autoplay
                loop
                src={lottieData} // <-- Pass the raw JSON object instead of the URL
                style={{ height: '300px', width: '300px' }}
              />
            </div>

            {/* Download Button remains the same */}
            <div className="flex justify-center gap-4">
              <a 
                href={`${API_BASE}/download/${jobId}`} 
                download="animation.json"
                className="bg-gray-900 text-white px-6 py-2 rounded-lg font-medium hover:bg-gray-800 transition"
              >
                Download JSON
              </a>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}