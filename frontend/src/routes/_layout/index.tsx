import {
  Alert,
  Box,
  Button,
  Container,
  Heading,
  HStack,
  Icon,
  Progress,
  Text,
  VStack,
} from "@chakra-ui/react"
import { createFileRoute } from "@tanstack/react-router"
import type React from "react"
import { useEffect, useRef, useState } from "react"
import {
  FiAlertCircle,
  FiCheckCircle,
  FiDownload,
  FiFileText,
  FiUpload,
} from "react-icons/fi"
import { DocumentService, TasksService, UtilsService } from "@/client"

export const Route = createFileRoute("/_layout/")({
  component: Dashboard,
})

interface UploadStatus {
  stage:
    | "idle"
    | "uploading"
    | "processing"
    | "converting"
    | "completed"
    | "error"
  message: string
  progress: number
  error?: string
}


function Dashboard() {
  const [uploadStatus, setUploadStatus] = useState<UploadStatus>({
    stage: "idle",
    message: "",
    progress: 0,
  })
  const [downloadUrl, setDownloadUrl] = useState<string>("")
  const [showDownload, setShowDownload] = useState(false)
  const [operationInfo, setOperationInfo] = useState<{
    gcp_processor_version: string
    gcp_project_id: string | null
    gcp_location: string
    gcp_processor_id: string | null
  } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const statusCheckInterval = useRef<NodeJS.Timeout | null>(null)
  const operationCheckInterval = useRef<NodeJS.Timeout | null>(null)
  const convertCheckInterval = useRef<NodeJS.Timeout | null>(null)

  // Fetch operation info on component mount
  useEffect(() => {
    const fetchOperationInfo = async () => {
      try {
        const info = await UtilsService.getOperationInfo()
        setOperationInfo(info)
      } catch (error) {
        console.error("Failed to fetch operation info:", error)
      }
    }
    fetchOperationInfo()
  }, [])

  const updateStatus = (
    stage: UploadStatus["stage"],
    message: string,
    progress: number = 0,
    error?: string,
  ) => {
    setUploadStatus({ stage, message, progress, error })
  }

  const clearIntervals = () => {
    if (statusCheckInterval.current) {
      clearInterval(statusCheckInterval.current)
      statusCheckInterval.current = null
    }
    if (operationCheckInterval.current) {
      clearInterval(operationCheckInterval.current)
      operationCheckInterval.current = null
    }
    if (convertCheckInterval.current) {
      clearInterval(convertCheckInterval.current)
      convertCheckInterval.current = null
    }
  }

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file && file.type === "application/pdf") {
      handleFileUpload(file)
    } else {
      updateStatus("error", "請選擇有效的 PDF 檔案", 0, "檔案格式不正確")
    }
  }

  const handleFileUpload = async (file: File) => {
    try {
      updateStatus("uploading", "正在準備上傳,請稍候...", 10)

      // Step 1: 請求簽名 URL
      const uploadResponse = await DocumentService.generateSignedUrlEndpoint({
        requestBody: {
          file_name: file.name,
          content_type: file.type,
        }
      })

      const { signed_url, file_key, file_name } = uploadResponse as any
      updateStatus("uploading", "檔案正在上傳中,請不要關閉此頁面...", 30)

      // Step 2: 直接上傳檔案到 GCS
      const gcsUploadResponse = await fetch(signed_url, {
        method: "PUT",
        body: file,
        headers: { "Content-Type": file.type },
      })

      if (!gcsUploadResponse.ok) {
        throw new Error(`上傳失敗: ${gcsUploadResponse.statusText}`)
      }

      updateStatus("processing", "上傳完成，正在排入處理佇列...", 50)

      // Step 3: 檔案上傳完成，通知後端開始處理任務
      const processResponse = await DocumentService.processUploadedFile({
        requestBody: {
          file_key,
          file_name,
        }
      })

      const { task_id } = processResponse as any
      updateStatus("processing", "處理任務已啟動，請稍候...", 60)

      // Step 4: 輪詢任務狀態
      statusCheckInterval.current = setInterval(async () => {
        try {
          const statusResponse = await TasksService.getTaskStatus({ taskId: task_id })
          const { status } = statusResponse

          if (status === "SUCCESS") {
            clearInterval(statusCheckInterval.current!)
            updateStatus("processing", "辨識完成，查詢作業狀態中...", 70)

            // Step 5: 取得任務結果以取得 operation_name，並輪詢作業狀態
            const resultResp = await TasksService.getTaskResult({ taskId: task_id }) as any
            const operationName = resultResp?.operation_name

            if (!operationName) {
              throw new Error("任務結果中沒有 operation_name")
            }

            operationCheckInterval.current = setInterval(async () => {
              try {
                const opResp =
                  await DocumentService.getOperation({ requestBody: { operation_name: operationName } }) as any
                const { done } = opResp

                if (done) {
                  clearInterval(operationCheckInterval.current!)
                  updateStatus("converting", "作業完成！可進行後續轉換。", 80)

                  // Step 6: 轉換處理過的JSON file 成 excel
                  const convertResponse = await DocumentService.convertProcessedFileToExcel({
                    requestBody: {
                      file_key,
                    }
                  })

                  const { task_id: convertTaskId } = convertResponse as any
                  updateStatus("converting", "轉換任務已啟動，請稍候...", 85)

                  convertCheckInterval.current = setInterval(async () => {
                    const convertStatusResponse =
                      await TasksService.getTaskStatus({ taskId: convertTaskId })
                    const { status } = convertStatusResponse

                    if (status === "SUCCESS") {
                      clearInterval(convertCheckInterval.current!)
                      updateStatus("completed", "轉換完成！", 100)

                      const resultResp =
                        await TasksService.getTaskResult({ taskId: convertTaskId })
                      const { gcs_download_path } = resultResp

                      if (gcs_download_path) {
                        setDownloadUrl(gcs_download_path)
                        setShowDownload(true)
                      }
                    } else if (status === "FAILURE") {
                      clearInterval(convertCheckInterval.current!)
                      updateStatus("error", "轉換失敗", 0, "轉換過程中發生錯誤")
                    } else {
                      updateStatus(
                        "converting",
                        `轉換中... (狀態: ${status})`,
                        90,
                      )
                    }
                  }, 5000)
                } else {
                  updateStatus("processing", "作業處理中，請稍候...", 75)
                }
              } catch (e) {
                clearInterval(operationCheckInterval.current!)
                updateStatus(
                  "error",
                  "查詢作業狀態失敗",
                  0,
                  (e as Error).message,
                )
              }
            }, 4000)
          } else if (status === "FAILURE") {
            clearInterval(statusCheckInterval.current!)
            updateStatus("error", "處理失敗", 0, "任務執行失敗")
          } else {
            updateStatus("processing", `處理中... (狀態: ${status})`, 65)
          }
        } catch (e) {
          clearInterval(statusCheckInterval.current!)
          updateStatus("error", "檢查任務狀態失敗", 0, (e as Error).message)
        }
      }, 5000)
    } catch (error) {
      updateStatus("error", "發生錯誤", 0, (error as Error).message)
      clearIntervals()
    }
  }

  const handleDownload = async () => {
    try {
      if (!downloadUrl) {
        throw new Error("下載 URL 不存在")
      }
      const response = await DocumentService.downloadFromGcs({ gcsDownloadPath: downloadUrl });
      if (
        typeof response !== "object" ||
        response === null ||
        !("signed_url" in response) ||
        !("file_name" in response)
      ) {
        throw new Error("無法取得下載連結或檔名");
      }
      const { signed_url: download_url, file_name: fileName } = response as { signed_url: string, file_name: string };
      fetch(download_url)
        .then(response => response.blob())
        .then(blob => {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = fileName; // set desired filename
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);
      });
    } catch (error) {
      updateStatus("error", "下載失敗", 0, (error as Error).message)
    }
  }

  const resetUpload = () => {
    clearIntervals()
    setUploadStatus({ stage: "idle", message: "", progress: 0 })
    setShowDownload(false)
    setDownloadUrl("")
    if (fileInputRef.current) {
      fileInputRef.current.value = ""
    }
  }

  const getStatusIcon = () => {
    switch (uploadStatus.stage) {
      case "completed":
        return <Icon as={FiCheckCircle} color="green.500" boxSize={5} />
      case "error":
        return <Icon as={FiAlertCircle} color="red.500" boxSize={5} />
      default:
        return <Icon as={FiFileText} color="blue.500" boxSize={5} />
    }
  }

  const getStatusColor = () => {
    switch (uploadStatus.stage) {
      case "completed":
        return "green.600"
      case "error":
        return "red.600"
      default:
        return "blue.600"
    }
  }

  return (
    <Container maxW="2xl" py={8}>
      <Heading size="lg" display="flex" alignItems="center" gap={2}>
        <Icon as={FiUpload} boxSize={6} />
        PDF BOM 表格轉換器
      </Heading>
      {/* Version Information */}
      {operationInfo && (
        <Box
          bg="gray.50"
          borderRadius="md"
          p={2}
          border="1px solid"
          borderColor="gray.200"
        >
          <Text fontSize="sm" color="gray.600" >
            目前使用的處理模型版本： {operationInfo.gcp_processor_version}
          </Text>
        </Box>
      )}
      <VStack align="stretch" mt={8}>
        {/* Upload Area - Only show when idle */}
      <Text color="gray.600">
        上傳您的 PDF BOM 表格，我們將為您轉換為 Excel 格式
      </Text>
      
      
        {uploadStatus.stage === "idle" && (
          <Box
            border="2px dashed"
            borderColor="gray.300"
            borderRadius="lg"
            p={8}
            textAlign="center"
            cursor="pointer"
            _hover={{ borderColor: "gray.400" }}
            transition="border-color 0.2s"
            onClick={() => fileInputRef.current?.click()}
          >
            <Icon as={FiUpload} boxSize={12} color="gray.400" mb={4} />
            <Text fontSize="lg" fontWeight="medium" color="gray.700" mb={2}>
              點擊或拖曳 PDF 檔案至此
            </Text>
            <Text fontSize="sm" color="gray.500">
              支援 PDF 格式，頁數限制 200 頁
            </Text>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf"
              onChange={handleFileSelect}
              style={{ display: "none" }}
            />
          </Box>
        )}

        {/* Progress Section */}
        {uploadStatus.stage !== "idle" && (
          <VStack align="stretch">
            <HStack>
              {getStatusIcon()}
              <Text fontWeight="medium" color={getStatusColor()}>
                {uploadStatus.message}
              </Text>
            </HStack>

            {uploadStatus.stage !== "error" && (
              <Progress.Root
                maxW="240px"
                value={uploadStatus.progress}
                colorPalette="blue"
                variant="subtle"
                size="lg"
              >
                <Progress.Track>
                  <Progress.Range />
                </Progress.Track>
              </Progress.Root>
            )}

            {uploadStatus.error && (
              <Alert.Root status="error" title={uploadStatus.error}>
                <Alert.Indicator />
                <Alert.Title>{uploadStatus.error}</Alert.Title>
              </Alert.Root>
            )}
          </VStack>
        )}

        {/* Download Button */}
        {showDownload && (
          <HStack gap={4}>
            <Icon as={FiDownload} />
            <Button onClick={handleDownload}>下載 Excel 檔案</Button>
            <Button variant="outline" onClick={resetUpload}>
              重新上傳
            </Button>
          </HStack>
        )}

        {/* Reset Button for Error State */}
        {uploadStatus.stage === "error" && (
          <Button variant="outline" onClick={resetUpload} width="full">
            重新上傳
          </Button>
        )}
      </VStack>
    </Container>
  )
}
