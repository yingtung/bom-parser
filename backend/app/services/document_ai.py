import pandas as pd
from google.api_core.client_options import ClientOptions
from google.cloud import documentai
from google.longrunning.operations_pb2 import GetOperationRequest, Operation
from google.oauth2.service_account import Credentials

from app.core.config import settings
from app.models.document import BOMShema, CPLShema, Items
from app.utils import logger


def layout_to_text(layout: documentai.Document.Page.Layout, text: str) -> str:
    """Convert layout offsets to text string."""
    return "".join(
        text[int(segment.start_index) : int(segment.end_index)]
        for segment in layout.text_anchor.text_segments
    )


def group_entities_by_position(
    entities: list[documentai.Document.Entity],
) -> list[dict[str, str]]:
    """Group entities by their vertical position (y coordinate) into rows."""
    if not entities:
        return []

    # Extract entities with y coordinates
    entities_with_pos = []
    for item in entities:
        bounding_poly = item.page_anchor.page_refs[0].bounding_poly
        vertices = bounding_poly.normalized_vertices
        if vertices:
            entities_with_pos.append(
                {
                    "entity": item,
                    "avg_y": sum(v.y for v in vertices) / len(vertices),
                    "avg_x": sum(v.x for v in vertices) / len(vertices),
                    "page": item.page_anchor.page_refs[0].page + 1,
                }
            )

    # Sort by page and y coordinates, y coordinates is the vertical position of the entity
    # so that we would parse the entity by the order of y coordinates
    entities_with_pos.sort(key=lambda item: (item["page"], item["avg_y"]))

    # Group by y coordinate
    grouped_items = []
    current_list = []

    if not entities_with_pos:
        return []

    y_threshold = 0.01
    current_y = entities_with_pos[0]["avg_y"]

    for item in entities_with_pos:
        if abs(item["avg_y"] - current_y) > y_threshold:
            # it means the entity is in the next row

            grouped_items.append(current_list)
            current_list = []
            current_y = item["avg_y"]
        current_list.append(item)
    grouped_items.append(current_list)

    grouped_rows = []
    current_row = {}
    page_line_no = {}  # page number and line number mapping
    for row_items in grouped_items:
        # sort the row_items by the avg_x
        row_items.sort(key=lambda item: item["avg_x"])
        for item in row_items:
            entity = item["entity"]
            entity_type = entity.type_
            mention_text = entity.mention_text
            page = str(item["page"])
            current_row["page"] = page

            if entity_type == "line-number":
                page_line_no[page] = mention_text
            elif entity_type not in current_row:
                current_row[entity_type] = mention_text
            else:
                # Because we sorted the row_items by the avg_x, so if the type duplicated, we should append the current_row to the grouped_rows
                grouped_rows.append(current_row)
                current_row = {}
                current_row[entity_type] = mention_text
        grouped_rows.append(current_row)
        current_row = {}

    if current_row:
        grouped_rows.append(current_row)

    for r in grouped_rows:
        r["line-number"] = page_line_no.get(r.get("page", ""), "")

    return grouped_rows


def entities_to_dataframe_by_row(
    entities: list[documentai.Document.Entity],
) -> pd.DataFrame:
    """Convert Document AI entities to DataFrame based on row position."""
    rows_data = group_entities_by_position(entities)
    return pd.DataFrame(rows_data)


def extract_items(document: documentai.Document) -> Items:
    """Extract BOM items from a processed document."""
    bom_items = []
    cpl_items = []

    # Extract entities and convert to DataFrame
    df = entities_to_dataframe_by_row(document.entities)
    df.fillna("", inplace=True)

    # Convert DataFrame rows to BOMShema objects
    for _, row in df.iterrows():
        line_no = str(row.get("line-number", ""))
        page = str(row.get("page", ""))
        bom_pt = str(row.get("BOM-pt", ""))
        bom_description = str(row.get("BOM-description", ""))
        bom_quantity = str(row.get("BOM-qty", ""))
        bom_size = str(row.get("BOM-size", ""))
        bom_item_code = str(row.get("BOM-item_code", ""))
        cpl_cut_piece = str(row.get("CPL-cut_piece", ""))
        cpl_length = str(row.get("CPL-length", ""))
        cpl_size = str(row.get("CPL-size", ""))

        if bool(bom_description) & (
            bool(bom_pt)
            | bool(bom_description)
            | bool(bom_quantity)
            | bool(bom_size)
            | bool(bom_item_code)
        ):
            bom_items.append(
                BOMShema(
                    page=page,
                    line_no=line_no,
                    bom_pt=bom_pt,
                    bom_description=bom_description,
                    bom_quantity=bom_quantity,
                    bom_size=bom_size,
                    bom_item_code=bom_item_code,
                )
            )
        if bool(cpl_cut_piece) | bool(cpl_length) | bool(cpl_size):
            cpl_items.append(
                CPLShema(
                    page=page,
                    line_no=line_no,
                    cpl_cut_piece=cpl_cut_piece,
                    cpl_length=cpl_length,
                    cpl_size=cpl_size,
                )
            )

    return Items(bom_items=bom_items, cpl_items=cpl_items)


class DocumentAIService:
    """Service for processing documents using Google Document AI."""

    def __init__(self):
        self.client = documentai.DocumentProcessorServiceClient(
            credentials=Credentials.from_service_account_file(
                settings.GOOGLE_APPLICATION_CREDENTIALS
            ),
            client_options=ClientOptions(
                api_endpoint=f"{settings.GCP_LOCATION}-documentai.googleapis.com"
            ),
        )

    def get_process_name(self):
        logger.info(f"Document AI Processor Version: {settings.GCP_PROCESSOR_VERSION}")
        return self.client.processor_version_path(
            settings.GCP_PROJECT_ID,
            settings.GCP_LOCATION,
            settings.GCP_PROCESSOR_ID,
            settings.GCP_PROCESSOR_VERSION,
        )

    def process_document(
        self,
        file_path: str,
        mime_type: str,
        process_options: documentai.ProcessOptions | None = None,
    ) -> documentai.Document:
        """Process a document using Document AI."""
        # The full resource name of the processor version
        name = self.get_process_name()

        # Read the file into memory
        with open(file_path, "rb") as image:
            image_content = image.read()

        # Configure the process request
        process_request = documentai.ProcessRequest(
            name=name,
            raw_document=documentai.RawDocument(
                content=image_content, mime_type=mime_type
            ),
            process_options=process_options,
        )

        result = self.client.process_document(request=process_request)
        return result.document

    def batch_process(
        self,
        gcs_input_uri: str,
        gcs_output_uri: str,
        field_mask: str | None = None,
    ):
        gcs_document = documentai.GcsDocument(
            gcs_uri=gcs_input_uri, mime_type="application/pdf"
        )
        # Load GCS Input URI into a List of document files
        gcs_documents = documentai.GcsDocuments(documents=[gcs_document])
        input_config = documentai.BatchDocumentsInputConfig(gcs_documents=gcs_documents)

        # 定義結果輸出位置 (可選，預設會輸出到一個臨時目錄)
        # Cloud Storage URI for the Output Directory
        gcs_output_config = documentai.DocumentOutputConfig.GcsOutputConfig(
            gcs_uri=gcs_output_uri, field_mask=field_mask
        )

        request = documentai.BatchProcessRequest(
            name=self.get_process_name(),
            input_documents=input_config,
            document_output_config=documentai.DocumentOutputConfig(
                gcs_output_config=gcs_output_config
            ),
        )
        # 觸發批次處理
        operation = self.client.batch_process_documents(request=request)
        return operation

    def get_operation(self, operation_name: str) -> Operation:
        # The format of operation_name is "projects/{project_id}/locations/{location}/operations/{operation_id}"

        request = GetOperationRequest(name=operation_name)
        operation = self.client.get_operation(request=request)
        return operation
