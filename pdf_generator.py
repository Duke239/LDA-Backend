import os
import io
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import inch, mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.pdfgen import canvas
from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, List
import logging

from quote_models import Quote

logger = logging.getLogger(__name__)

class QuotePDFGenerator:
    def __init__(self):
        self.page_width, self.page_height = A4
        self.margin = 20 * mm
        self.content_width = self.page_width - (2 * self.margin)
        
        # Company information from environment
        self.company_name = os.getenv("COMPANY_NAME", "LDA Group")
        self.company_address = os.getenv("COMPANY_ADDRESS", "")
        self.company_email = os.getenv("COMPANY_EMAIL", "")
        self.company_phone = os.getenv("COMPANY_PHONE", "")
        self.company_logo_path = os.getenv("COMPANY_LOGO_PATH", "")
        
        # LDA Group brand colors
        self.brand_red = colors.HexColor('#D11F2F')  # LDA red
        self.dark_grey = colors.HexColor('#333333')
        self.light_grey = colors.HexColor('#F5F5F5')
        
        # Setup styles
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()
    
    def _setup_custom_styles(self):
        """Setup custom paragraph styles with LDA branding"""
        # Company name style
        self.styles.add(ParagraphStyle(
            name='CompanyName',
            parent=self.styles['Heading1'],
            fontSize=24,
            textColor=self.brand_red,
            spaceAfter=6,
            fontName='Helvetica-Bold'
        ))
        
        # Quote header style
        self.styles.add(ParagraphStyle(
            name='QuoteHeader',
            parent=self.styles['Heading2'],
            fontSize=20,
            textColor=self.dark_grey,
            spaceAfter=12,
            fontName='Helvetica-Bold',
            alignment=TA_RIGHT
        ))
        
        # Section header style
        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=self.styles['Heading3'],
            fontSize=14,
            textColor=self.brand_red,
            spaceBefore=12,
            spaceAfter=6,
            fontName='Helvetica-Bold',
            borderColor=self.brand_red,
            borderWidth=1,
            borderPadding=4
        ))
        
        # Client info style
        self.styles.add(ParagraphStyle(
            name='ClientInfo',
            parent=self.styles['Normal'],
            fontSize=11,
            spaceAfter=6,
            leftIndent=0
        ))
        
        # Footer style
        self.styles.add(ParagraphStyle(
            name='Footer',
            parent=self.styles['Normal'],
            fontSize=8,
            textColor=colors.grey,
            alignment=TA_CENTER
        ))
    
    def generate_quote_pdf(self, quote: Quote) -> bytes:
        """Generate professional quote PDF with LDA branding"""
        try:
            buffer = io.BytesIO()
            doc = SimpleDocTemplate(
                buffer,
                pagesize=A4,
                rightMargin=self.margin,
                leftMargin=self.margin,
                topMargin=self.margin,
                bottomMargin=self.margin
            )
            
            # Build PDF content
            story = []
            story.extend(self._build_header(quote))
            story.append(Spacer(1, 20))
            story.extend(self._build_quote_info(quote))
            story.append(Spacer(1, 15))
            story.extend(self._build_client_info(quote))
            story.append(Spacer(1, 20))
            story.extend(self._build_job_description(quote))
            story.append(Spacer(1, 15))
            
            if quote.materials:
                story.extend(self._build_materials_section(quote))
                story.append(Spacer(1, 15))
            
            story.extend(self._build_labor_section(quote))
            story.append(Spacer(1, 15))
            story.extend(self._build_totals_section(quote))
            story.append(Spacer(1, 20))
            story.extend(self._build_terms_conditions(quote))
            story.extend(self._build_footer())
            
            # Build PDF
            doc.build(story, onFirstPage=self._add_page_number, onLaterPages=self._add_page_number)
            
            buffer.seek(0)
            return buffer.read()
            
        except Exception as e:
            logger.error(f"Failed to generate PDF for quote {quote.quote_number}: {str(e)}")
            raise
    
    def _build_header(self, quote: Quote) -> List:
        """Build header with logo and company info"""
        elements = []
        
        # Header table with logo and company info on left, quote info on right
        header_data = []
        
        # Left side content
        left_content = []
        
        # Add company logo if available
        if self.company_logo_path and os.path.exists(self.company_logo_path):
            try:
                logo = Image(self.company_logo_path, width=50*mm, height=25*mm)
                logo.hAlign = 'LEFT'
                left_content.append(logo)
                left_content.append(Spacer(1, 5))
            except Exception as e:
                logger.warning(f"Failed to load logo: {e}")
        
        # Company name and info
        company_info = Paragraph(self.company_name, self.styles['CompanyName'])
        left_content.append(company_info)
        
        company_details = f"""
        {self.company_address}<br/>
        T: {self.company_phone}<br/>
        E: {self.company_email}
        """
        company_para = Paragraph(company_details, self.styles['Normal'])
        left_content.append(company_para)
        
        # Right side - Quote info
        quote_info = f"""
        <para alignment="right" fontSize="20" textColor="#D11F2F">
        <b>QUOTATION</b>
        </para>
        <para alignment="right">
        Quote #: {quote.quote_number}<br/>
        Date: {quote.created_at.strftime('%d/%m/%Y')}<br/>
        Valid Until: {quote.valid_until.strftime('%d/%m/%Y')}<br/>
        Surveyor: {quote.surveyor_name}
        </para>
        """
        
        # Create header table
        header_table = Table(
            [[left_content, Paragraph(quote_info, self.styles['Normal'])]],
            colWidths=[self.content_width * 0.6, self.content_width * 0.4]
        )
        
        header_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 15),
        ]))
        
        elements.append(header_table)
        
        return elements
    
    def _build_quote_info(self, quote: Quote) -> List:
        """Build quote information section"""
        elements = []
        
        quote_details = [
            ['Quote Number:', quote.quote_number],
            ['Created:', quote.created_at.strftime('%d/%m/%Y')],
            ['Valid Until:', quote.valid_until.strftime('%d/%m/%Y')],
            ['Status:', quote.status.title()],
        ]
        
        info_table = Table(quote_details, colWidths=[40*mm, 50*mm])
        info_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        
        elements.append(info_table)
        return elements
    
    def _build_client_info(self, quote: Quote) -> List:
        """Build client information section"""
        elements = []
        
        elements.append(Paragraph("Client Information", self.styles['SectionHeader']))
        
        client_info = f"""
        <b>{quote.client.company or quote.client.name}</b><br/>
        {quote.client.name if quote.client.company else ""}<br/>
        {quote.client.address}<br/>
        T: {quote.client.phone}<br/>
        E: {quote.client.email}
        """
        
        elements.append(Paragraph(client_info, self.styles['ClientInfo']))
        return elements
    
    def _build_job_description(self, quote: Quote) -> List:
        """Build job description section"""
        elements = []
        
        elements.append(Paragraph("Job Description", self.styles['SectionHeader']))
        elements.append(Paragraph(quote.job_description, self.styles['Normal']))
        
        return elements
    
    def _build_materials_section(self, quote: Quote) -> List:
        """Build materials section"""
        elements = []
        
        if not quote.materials:
            return elements
            
        elements.append(Paragraph("Materials", self.styles['SectionHeader']))
        
        # Table headers
        table_data = [['Description', 'Quantity', 'Unit Price', 'Total']]
        
        # Add materials
        for material in quote.materials:
            table_data.append([
                material.description,
                f"{material.quantity:,.2f}",
                f"£{material.unit_price:,.2f}",
                f"£{material.total:,.2f}"
            ])
        
        # Create table
        materials_table = Table(table_data, colWidths=[80*mm, 25*mm, 30*mm, 30*mm])
        
        # Style table
        materials_table.setStyle(TableStyle([
            # Header row
            ('BACKGROUND', (0, 0), (-1, 0), self.brand_red),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            
            # Data rows
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, self.light_grey]),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))
        
        elements.append(materials_table)
        return elements
    
    def _build_labor_section(self, quote: Quote) -> List:
        """Build labor section"""
        elements = []
        
        elements.append(Paragraph("Labor", self.styles['SectionHeader']))
        
        # Table headers
        table_data = [['Description', 'Hours/Qty', 'Rate', 'Total']]
        
        # Add estimated hours
        labor_cost = Decimal(str(quote.estimated_hours)) * quote.hourly_rate
        table_data.append([
            'Labor (Estimated)',
            f"{quote.estimated_hours:,.2f} hours",
            f"£{quote.hourly_rate:,.2f}/hour",
            f"£{labor_cost:,.2f}"
        ])
        
        # Add additional labor items
        for item in quote.labor_items:
            table_data.append([
                item.description,
                f"{item.quantity:,.2f}",
                f"£{item.unit_price:,.2f}",
                f"£{item.total:,.2f}"
            ])
        
        # Create table
        labor_table = Table(table_data, colWidths=[80*mm, 25*mm, 30*mm, 30*mm])
        
        # Style table
        labor_table.setStyle(TableStyle([
            # Header row
            ('BACKGROUND', (0, 0), (-1, 0), self.brand_red),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            
            # Data rows
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, self.light_grey]),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))
        
        elements.append(labor_table)
        return elements
    
    def _build_totals_section(self, quote: Quote) -> List:
        """Build totals section"""
        elements = []
        
        # Totals table
        totals_data = [
            ['Subtotal:', f"£{quote.subtotal:,.2f}"],
            [f'VAT ({quote.tax_rate * 100:.0f}%):', f"£{quote.tax_amount:,.2f}"],
            ['Total:', f"£{quote.total_amount:,.2f}"],
        ]
        
        totals_table = Table(totals_data, colWidths=[120*mm, 45*mm])
        totals_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -2), 'Helvetica'),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 12),
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('LINEBELOW', (0, -1), (-1, -1), 2, self.brand_red),
            ('BACKGROUND', (0, -1), (-1, -1), self.light_grey),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        
        elements.append(totals_table)
        return elements
    
    def _build_terms_conditions(self, quote: Quote) -> List:
        """Build terms and conditions"""
        elements = []
        
        elements.append(Paragraph("Terms and Conditions", self.styles['SectionHeader']))
        
        terms = quote.terms_conditions or """
        This quote is valid for 30 days from the date above.
        Payment terms: Net 30 days from completion.
        Work will commence upon receipt of signed acceptance.
        Any changes to the scope of work may result in additional charges.
        """
        
        elements.append(Paragraph(terms, self.styles['Normal']))
        
        if quote.notes:
            elements.append(Spacer(1, 10))
            elements.append(Paragraph("Additional Notes", self.styles['SectionHeader']))
            elements.append(Paragraph(quote.notes, self.styles['Normal']))
        
        return elements
    
    def _build_footer(self) -> List:
        """Build footer"""
        elements = []
        
        elements.append(Spacer(1, 30))
        footer_text = f"Thank you for choosing {self.company_name}. We look forward to working with you."
        elements.append(Paragraph(footer_text, self.styles['Footer']))
        
        return elements
    
    def _add_page_number(self, canvas, doc):
        """Add page number to each page"""
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        canvas.drawRightString(
            self.page_width - self.margin,
            self.margin / 2,
            f"Page {doc.page}"
        )
        canvas.restoreState()