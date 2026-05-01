from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, Float, DateTime, ForeignKey, Text, Enum
from sqlalchemy.orm import relationship
import enum

from .database import Base


class ProcessingStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    confirmed = "confirmed"


class ConfirmResult(str, enum.Enum):
    approved = "approved"
    rejected = "rejected"


class DimensionType(str, enum.Enum):
    linear = "linear"          # 线性尺寸
    diameter = "diameter"      # 直径
    radius = "radius"          # 半径
    angle = "angle"            # 角度
    gdt = "gdt"                # 形位公差
    roughness = "roughness"    # 表面粗糙度
    reference = "reference"    # 参考尺寸


class DimensionSource(str, enum.Enum):
    program = "program"        # pdfplumber 提取
    llm = "llm"                # Claude Vision 补充


class ReviewStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    questionable = "questionable"
    rejected = "rejected"


class Part(Base):
    __tablename__ = "parts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    drawing_number = Column(String(100), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    versions = relationship("Version", back_populates="part", order_by="Version.created_at.desc()")


class Version(Base):
    __tablename__ = "versions"

    id = Column(Integer, primary_key=True, index=True)
    part_id = Column(Integer, ForeignKey("parts.id"), nullable=False)
    version_code = Column(String(50), nullable=False)  # A, B, C or v1, v2
    is_current = Column(Boolean, default=True)
    status = Column(Enum(ProcessingStatus), default=ProcessingStatus.pending)
    confirm_result = Column(Enum(ConfirmResult), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    confirmed_at = Column(DateTime, nullable=True)

    part = relationship("Part", back_populates="versions")
    drawings = relationship("Drawing", back_populates="version", order_by="Drawing.sequence")


class Drawing(Base):
    __tablename__ = "drawings"

    id = Column(Integer, primary_key=True, index=True)
    version_id = Column(Integer, ForeignKey("versions.id"), nullable=False)
    sequence = Column(Integer, nullable=False, default=1)  # 第几张
    filename = Column(String(255), nullable=False)
    gdrive_file_id = Column(String(100), nullable=True)    # Google Drive file ID
    annotated_image_id = Column(String(100), nullable=True) # 标注 JPG 的 GDrive ID
    created_at = Column(DateTime, default=datetime.utcnow)

    version = relationship("Version", back_populates="drawings")
    dimensions = relationship("Dimension", back_populates="drawing")


class Dimension(Base):
    __tablename__ = "dimensions"

    id = Column(Integer, primary_key=True, index=True)
    drawing_id = Column(Integer, ForeignKey("drawings.id"), nullable=False)
    sequence = Column(Integer, nullable=False)             # 序号，对应标注图圆圈
    value = Column(String(100), nullable=False)            # 原始字符串，如 "69.5 ±0.4"
    nominal = Column(Float, nullable=True)                 # 数值部分
    tolerance = Column(String(50), nullable=True)          # 公差部分
    dim_type = Column(Enum(DimensionType), nullable=False)
    view_name = Column(String(100), nullable=True)         # 所在视图，如"主视图"
    source = Column(Enum(DimensionSource), nullable=False)
    # 在标注 JPG 中的坐标（像素）
    anchor_x = Column(Float, nullable=True)
    anchor_y = Column(Float, nullable=True)
    review_status = Column(Enum(ReviewStatus), default=ReviewStatus.pending)

    drawing = relationship("Drawing", back_populates="dimensions")
    messages = relationship("ReviewMessage", back_populates="dimension", order_by="ReviewMessage.created_at")


class ReviewMessage(Base):
    __tablename__ = "review_messages"

    id = Column(Integer, primary_key=True, index=True)
    dimension_id = Column(Integer, ForeignKey("dimensions.id"), nullable=False)
    author = Column(String(100), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    dimension = relationship("Dimension", back_populates="messages")
