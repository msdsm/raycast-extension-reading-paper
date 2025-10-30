import { Detail, Clipboard, showToast, Toast } from "@raycast/api"
import { useEffect, useState } from "react"

const API_URL = "http://localhost:8000"

interface StreamEvent { 
    type: "text" | "tool_result" | "error" | "done"
    content?: string
}

export default function Command() {
    const [selectedText, setSelectedText] = useState<string>("")
    const [isLoading, setIsLoading] = useState<boolean>(true)
    const [streamedContent, setStreamedContent] = useState<string>("")
    const [error, setError] = useState<string | null>(null)
    const [toolResults, setToolResults] = useState<string[]>([])
    const [apiErrors, setApiErrors] = useState<string[]>([])

    useEffect(() => {
        const componentId = Math.random().toString(36).substr(2, 9)
        
        let isMounted = true;
        let hasExecuted = false;
        
        async function fetchClipboardText() {
            if (!isMounted || hasExecuted) return;
            hasExecuted = true;
            
            try {
                const text = await Clipboard.readText()
                
                if (!isMounted) return;
                
                if (!text || text.trim() === "") {
                    throw new Error("No text found in clipboard. Please copy a research term first.")
                }
                
                setSelectedText(text)

                if (!isMounted) return

                await analyzeTextWithStreaming(text)
            } catch (err) {
                if (!isMounted) return;
                
                const errorMessage = err instanceof Error ? err.message : String(err)
                setError(errorMessage)
                showToast({
                    style: Toast.Style.Failure,
                    title: "Error",
                    message: errorMessage,
                })
            } finally {
                if (isMounted) {
                    setIsLoading(false)
                }
            }
        }
        
        fetchClipboardText()
        
        return () => {
            isMounted = false;
        }
    }, [])

    async function analyzeTextWithStreaming(text: string) {
        try {
            const response = await fetch(`${API_URL}/explain-research-term`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({ text }),
            })

            if (!response.ok || !response.body) {
                throw new Error(`API request failed with status ${response.statusText}`)
            }

            const reader = response.body.getReader()
            const decoder = new TextDecoder()

            if (!reader) {
                throw new Error("ReadableStreamReader is not supported in this environment.")
            }

            let buffer = ""
            let accumulatedContent = ""

            while (true) {
                const { done, value } = await reader.read()
                
                if (done) {
                    break
                }

                buffer += decoder.decode(value, { stream: true })

                const lines = buffer.split("\n")
                buffer = lines.pop() || ""

                for (const line of lines) {
                    if (line.startsWith("data: ")) {
                        const data = line.slice(6)

                        try {
                            const event: StreamEvent = JSON.parse(data)

                            if (event.type === "text" && event.content) {
                                accumulatedContent += event.content
                                setStreamedContent(accumulatedContent)
                            } else if (event.type === "tool_result" && event.content) {
                                setToolResults(prev => [...prev, event.content!])
                            } else if (event.type === "error" && event.content) {
                                setApiErrors(prev => [...prev, event.content!])
                            } else if (event.type === "done") {
                                setIsLoading(false)
                            }
                        } catch (error) {
                            console.error("Error parsing stream event:", error)
                        }
                    }
                }
            }

            showToast({
                style: Toast.Style.Success,
                title: "Analysis Complete",
                message: "Text analysis completed successfully.",
            })
        } catch (err) {
            const errorMessage = err instanceof Error ? err.message : String(err)
            setError(errorMessage)
            throw err
        }
    }

    if (error) {
        return (
            <Detail
                markdown={`# Error\n\n${error}\n\n## Clipboard Text\n\n${selectedText}`}
                metadata={
                    <Detail.Metadata>
                        <Detail.Metadata.Label title="Status" text="Error" />
                    </Detail.Metadata>
                }
            />
        )
    }

    const markdown = `# Research Term Explanation\n\n${
        isLoading && !streamedContent
        ? "🔄 Searching arXiv and explaining the term...\n\nPlease wait while we analyze research papers and generate an explanation."
        : streamedContent || "No response yet..."
    }\n\n---\n\n## Selected Term\n\n${selectedText}`

    return (
        <Detail
            isLoading={isLoading && !streamedContent}
            markdown={markdown}
            metadata={
                <Detail.Metadata>
                    <Detail.Metadata.Label title="Status" text={isLoading ? "Processing..." : "Complete"} />
                    <Detail.Metadata.Separator />
                    <Detail.Metadata.Label title="API" text="arXiv + Claude" />
                    
                    {toolResults.length > 0 && (
                        <>
                            <Detail.Metadata.Separator />
                            <Detail.Metadata.Label 
                                title="Tool Results" 
                                text={`${toolResults.length} result(s)`} 
                            />
                            {toolResults.map((result, index) => (
                                <Detail.Metadata.Label 
                                    key={index}
                                    title={`Tool ${index + 1}`} 
                                    text={result.length > 50 ? `${result.substring(0, 50)}...` : result} 
                                />
                            ))}
                        </>
                    )}
                    
                    {apiErrors.length > 0 && (
                        <>
                            <Detail.Metadata.Separator />
                            <Detail.Metadata.Label 
                                title="API Errors" 
                                text={`${apiErrors.length} error(s)`} 
                                icon="⚠️"
                            />
                            {apiErrors.map((errorMsg, index) => (
                                <Detail.Metadata.Label 
                                    key={index}
                                    title={`Error ${index + 1}`} 
                                    text={errorMsg.length > 50 ? `${errorMsg.substring(0, 50)}...` : errorMsg}
                                    icon="❌"
                                />
                            ))}
                        </>
                    )}
                </Detail.Metadata>
            }
        />
    )
}