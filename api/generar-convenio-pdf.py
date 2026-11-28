# api/generar-convenio-pdf.py
"""
API Serverless para generar PDFs de convenios - CON TARIFAS DINÁMICAS
Plantilla 2026 - VERSIÓN DEFINITIVA FINAL
Diseñada para Vercel
"""

from http.server import BaseHTTPRequestHandler
import json
import base64
import os
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader
from io import BytesIO


# ─────────────────────────────────────────────────────────────────
#  CONSTANTES DE LAYOUT
#  Medidas calculadas con pdfmetrics para fuente Kodchasan 12pt:
#    "Habitación Sencilla King:" → 146.8 pts desde INDENT
#    "Habitación Doble Queen:"   → 148.6 pts desde INDENT
#  PRICE_COL = INDENT + 148.6 + 12 (gap) = 240  (columna fija)
#  POR_NOCHE_X = PRICE_COL + ancho aprox "$1.480,00" + gap
# ─────────────────────────────────────────────────────────────────
LEFT         = 60    # margen izquierdo del cuerpo
INDENT       = 80    # sangría habitaciones / bullets
SUB_INDENT   = 94    # sangría para "Para X personas"
PRICE_COL    = 240   # columna X FIJA para valores de precio
POR_NOCHE_X  = 340   # columna X FIJA para "  por noche"
SIGN_LEFT    = 80    # firma izquierda (Ricardo Peña)
SIGN_RIGHT   = 310   # firma derecha   (cliente)


def registrar_fuente(dir_api):
    """Registra Kodchasan desde el directorio de la API; fallback a Helvetica."""
    try:
        font_path = os.path.join(dir_api, 'Kodchasan-Medium.ttf')
        pdfmetrics.registerFont(TTFont('Kodchasan', font_path))
        print("Fuente Kodchasan registrada")
        return 'Kodchasan'
    except Exception as e:
        print(f"Kodchasan no disponible ({e}); usando Helvetica")
        return 'Helvetica'


def fmt_tarifa(val):
    """Formato moneda estilo MX: $1.000,00"""
    s = f"${val:,.2f}"
    return s.replace(',', '_').replace('.', ',').replace('_', '.')


# Calendario 2027: desde INICIO_ANIO_2027 los documentos se llaman "2027" (enero 2027 conserva las tarifas 2026);
# desde INICIO_PLANTILLA_2027 aplican las tarifas nuevas (tarifas-2027.json).
INICIO_ANIO_2027 = '2027-01-01'
INICIO_PLANTILLA_2027 = '2027-02-01'


def anio_plantilla(fecha):
    # ponytail: año de la plantilla según la fecha del convenio (2027 desde INICIO_PLANTILLA_2027)
    return '2027' if fecha >= INICIO_ANIO_2027 else '2026'


def tarifas_para(fecha, tipo='hotel'):
    # Tarifas que se aplican a un convenio con esa fecha (para registrarlas en las hojas de n8n)
    dir_api = os.path.dirname(os.path.abspath(__file__))
    archivo = 'tarifas-2027.json' if fecha >= INICIO_PLANTILLA_2027 else 'tarifas.json'
    with open(os.path.join(dir_api, archivo), 'r', encoding='utf-8') as f:
        td = json.load(f)
    b = td['tarifasVillas'] if tipo == 'villas' else td['tarifas']
    return {
        'kingSin': b['habitacionKingSinDesayuno'], 'queenSin': b['habitacionQueenSinDesayuno'],
        'kingAmericano': b['habitacionKingDesayunoAmericano'], 'queenAmericano': b['habitacionQueenDesayunoAmericano'],
        'kingBuffet': b['habitacionKingDesayunoBuffet'], 'queenBuffet': b['habitacionQueenDesayunoBuffet'],
    }


def crear_convenio_pdf(numero_convenio, cliente, fecha, tarifas=None, año_vigencia=None, tipo='hotel'):
    """
    Genera el PDF del convenio Avanta 2026.
    - Tipografia Kodchasan
    - Logo y pie de pagina desde imagen
    - 3 bloques de tarifas: Sin desayuno / Americano / Buffet
    - Precios alineados en columna FIJA (PRICE_COL)
    - Subtextos con sangria propia (SUB_INDENT)
    - Firmas en dos columnas (SIGN_LEFT / SIGN_RIGHT)
    - Nombre de archivo: Convenio_(Empresa).pdf
    """

    dir_api = os.path.dirname(os.path.abspath(__file__))
    fuente  = registrar_fuente(dir_api)

    desde_txt = None  # texto de inicio de vigencia (solo plantilla 2027)
    villas = (tipo == 'villas')  # versión Villas: usa tarifasVillas y etiqueta 'Villa'
    etq = 'Villa' if villas else 'Habitación'
    # ── TARIFAS ──────────────────────────────────────────────────
    if tarifas is None:
        try:
            archivo = 'tarifas-2027.json' if fecha >= INICIO_PLANTILLA_2027 else 'tarifas.json'
            with open(os.path.join(dir_api, archivo), 'r', encoding='utf-8') as f:
                td = json.load(f)
            desde_txt = td.get('vigenciaDesdeTexto')
            base = td['tarifasVillas'] if villas else td['tarifas']
            tarifas = {
                'kingSin':        base['habitacionKingSinDesayuno'],
                'queenSin':       base['habitacionQueenSinDesayuno'],
                'kingAmericano':  base['habitacionKingDesayunoAmericano'],
                'queenAmericano': base['habitacionQueenDesayunoAmericano'],
                'kingBuffet':     base['habitacionKingDesayunoBuffet'],
                'queenBuffet':    base['habitacionQueenDesayunoBuffet'],
            }
            if año_vigencia is None:
                año_vigencia = td['version']
            print(f"Tarifas cargadas: {tarifas}")
        except Exception as e:
            print(f"tarifas.json no disponible ({e}); usando defaults")
            tarifas = {
                'kingSin': 800,       'queenSin': 1000,
                'kingAmericano': 965, 'queenAmericano': 1330,
                'kingBuffet': 1040,   'queenBuffet': 1480,
            }

    if año_vigencia is None:
        año_vigencia = str(datetime.now().year)

    # ── CANVAS ───────────────────────────────────────────────────
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter            # 612 x 792 pts
    RIGHT = width - 60                # 552

    negro = HexColor('#333333')
    gris  = HexColor('#888888')

    c.setFillColor(negro)
    y = height - 55                   # posicion Y inicial

    # ════════════════════════════════════════════════════════════
    #  LOGO
    # ════════════════════════════════════════════════════════════
    try:
        logo_path = os.path.join(dir_api, 'logo_avanta_principal.jpg')
        if not os.path.exists(logo_path):
            logo_path = os.path.join(dir_api, 'logo_avanta_principal.png')
        c.drawImage(ImageReader(logo_path), LEFT, y - 20,
                    width=150, height=60, preserveAspectRatio=True, mask='auto')
    except Exception as e:
        print(f"Logo no cargado: {e}")
        c.setFont(fuente, 18)
        c.drawString(LEFT, y, 'AVANTA Hotel & Villas')

    # ════════════════════════════════════════════════════════════
    #  FECHA (alineada a la derecha)
    # ════════════════════════════════════════════════════════════
    meses = {
        'January':'enero',   'February':'febrero', 'March':'marzo',
        'April':'abril',     'May':'mayo',          'June':'junio',
        'July':'julio',      'August':'agosto',     'September':'septiembre',
        'October':'octubre', 'November':'noviembre','December':'diciembre',
    }
    fecha_str = datetime.strptime(fecha, '%Y-%m-%d').strftime('%d de %B de %Y')
    for en, es in meses.items():
        fecha_str = fecha_str.replace(en, es)

    c.setFont(fuente, 12)
    c.drawString(RIGHT - c.stringWidth(fecha_str, fuente, 12), y, fecha_str)

    y -= 75

    # ════════════════════════════════════════════════════════════
    #  DATOS DEL CLIENTE
    # ════════════════════════════════════════════════════════════
    nombre_completo = f"{cliente.get('nombre','')} {cliente.get('apellidos','')}".strip()
    empresa         = cliente.get('empresa', 'Empresa')

    # Helper: parte texto largo en líneas que caben dentro del margen derecho
    def draw_wrapped(text, x, size=12, line_h=15):
        nonlocal y
        max_w = RIGHT - x
        words = text.split()
        line_words = []
        wrapped = []
        for word in words:
            test = ' '.join(line_words + [word])
            if pdfmetrics.stringWidth(test, fuente, size) <= max_w:
                line_words.append(word)
            else:
                wrapped.append(' '.join(line_words))
                line_words = [word]
        if line_words:
            wrapped.append(' '.join(line_words))
        c.setFont(fuente, size)
        for ln in wrapped:
            c.drawString(x, y, ln)
            y -= line_h

    c.setFont(fuente, 12)
    c.setFillColor(negro)
    c.drawString(LEFT, y, nombre_completo)
    y -= 18
    if villas:
        titulo = f"Convenio Villas {anio_plantilla(fecha)} con {empresa}"
    elif anio_plantilla(fecha) == '2027':  # plantilla 2027: los dos convenios se nombran Hotel / Villas
        titulo = f"Convenio Hotel 2027 con {empresa}"
    else:
        titulo = f"Convenio Avanta con {empresa}"
    c.drawString(LEFT, y, titulo)
    y -= 22
    c.drawString(LEFT, y, 'Por parte de Avanta Hotel & Villas.')
    y -= 15
    # Wrap dinámico: evita desbordamiento con nombres de empresa largos
    draw_wrapped(
        (f"Encontrará nuestros planes de hospedaje en Villas, flexibles y especiales para {empresa}" if villas
         else f"Encontrará nuestros planes de hospedaje flexibles especiales para {empresa}"),
        LEFT, size=12, line_h=15
    )
    y -= 13

    # ════════════════════════════════════════════════════════════
    #  HELPER: bloque de tarifas con columna de precios alineada
    # ════════════════════════════════════════════════════════════
    def bloque_tarifas(titulo, king_val, queen_val, king_pers, queen_pers):
        nonlocal y

        # Título del bloque
        c.setFont(fuente, 12)
        c.setFillColor(negro)
        c.drawString(LEFT, y, titulo)
        y -= 18

        def fila(label, valor):
            nonlocal y
            c.setFont(fuente, 12)
            c.setFillColor(negro)
            # Etiqueta (izquierda fija)
            c.drawString(INDENT, y, label)
            # Precio (columna fija — independiente del largo de la etiqueta)
            c.drawString(PRICE_COL, y, fmt_tarifa(valor))
            # "  por noche" (columna fija a continuacion del precio)
            c.drawString(POR_NOCHE_X, y, '  por noche')

        def sub(texto):
            nonlocal y
            y -= 13
            c.setFillColor(gris)
            c.setFont(fuente, 10)
            c.drawString(SUB_INDENT, y, texto)
            y -= 14
            c.setFillColor(negro)

        fila(f'{etq} Sencilla King:', king_val)
        sub(king_pers)
        fila(f'{etq} Doble Queen:', queen_val)
        sub(queen_pers)
        y -= 6

    # ── Bloque 1: Sin desayuno ───────────────────────────────────
    bloque_tarifas('Tarifas sin desayuno',
                   tarifas['kingSin'],       tarifas['queenSin'],
                   'Para 1 o 2 personas',    'Para 2 personas')

    # ── Bloque 2: Desayuno Americano ─────────────────────────────
    bloque_tarifas('Tarifas con desayuno Americano',
                   tarifas['kingAmericano'], tarifas['queenAmericano'],
                   'Para 1 persona',         'Para 2 personas')

    # ── Bloque 3: Desayuno Buffet ────────────────────────────────
    bloque_tarifas('Tarifas con desayuno Buffet',
                   tarifas['kingBuffet'],    tarifas['queenBuffet'],
                   'Para 1 persona',         'Para 2 personas')

    # ════════════════════════════════════════════════════════════
    #  SERVICIOS
    # ════════════════════════════════════════════════════════════
    c.setFont(fuente, 12)
    c.setFillColor(negro)
    c.drawString(LEFT, y, 'Ofrecemos servicios de:')
    y -= 18

    for srv in [
        'Wi-Fi de alta velocidad gratuito',
        'Sala de reuniones y espacio de trabajo para hasta 12 personas',
        'Estacionamiento gratuito',
    ]:
        c.drawString(INDENT, y, f"• {srv}")
        y -= 15
    y -= 10

    # ════════════════════════════════════════════════════════════
    #  ESPECIFICACIONES
    # ════════════════════════════════════════════════════════════
    c.drawString(LEFT, y, 'Especificaciones de tarifas convenio:')
    y -= 18

    if desde_txt:  # plantilla 2027: vigencia con fecha de inicio
        lineas_vigencia = [
            f"Tarifa vigente del {desde_txt} al 31 de diciembre de {año_vigencia}.",
            "A partir de esa fecha el presente convenio continuará (no tiene vencimiento)",
            "con las respectivas actualizaciones de tarifa y documento",
        ]
    elif anio_plantilla(fecha) == '2027':  # enero 2027: documento 2027 con tarifas 2026
        lineas_vigencia = [
            "Tarifa vigente hasta el 31 de enero de 2027. A partir de esa fecha el presente",
            "convenio continuará (no tiene vencimiento) con las respectivas actualizaciones",
            "de tarifa y documento",
        ]
    else:
        lineas_vigencia = [
            f"Tarifa vigente hasta el 31 de diciembre de {año_vigencia}. A partir de esa fecha el presente",
            "convenio continuará (no tiene vencimiento) con las respectivas actualizaciones",
            "de tarifa y documento",
        ]

    for linea in [
        "La tarifa convenio está disponible únicamente para reservaciones realizadas",
        "directamente con el hotel, a través de nuestro motor de reservaciones con",
        "el código Promocional: AVANTA",
        *lineas_vigencia,
        "Todas las reservaciones están sujetas a disponibilidad.",
    ]:
        c.drawString(LEFT, y, linea)
        y -= 15
    y -= 14

    # ════════════════════════════════════════════════════════════
    #  DESPEDIDA
    # ════════════════════════════════════════════════════════════
    c.drawString(LEFT, y, 'Agradecemos su confianza.')
    y -= 50

    # ════════════════════════════════════════════════════════════
    #  FIRMAS  (dos columnas alineadas)
    # ════════════════════════════════════════════════════════════
    c.setFont(fuente, 11)
    c.drawString(SIGN_LEFT,  y, 'Ricardo Peña Covarrubias')
    c.drawString(SIGN_RIGHT, y, nombre_completo)
    y -= 15
    c.drawString(SIGN_LEFT,  y, 'Avanta Hotel & Villas')
    c.drawString(SIGN_RIGHT, y, empresa)

    # ════════════════════════════════════════════════════════════
    #  PIE DE PÁGINA (imagen al fondo)
    # ════════════════════════════════════════════════════════════
    try:
        pie_path = os.path.join(dir_api, 'pie_de_pagina.jpg')
        if not os.path.exists(pie_path):
            pie_path = os.path.join(dir_api, 'pie_de_pagina.png')
        c.drawImage(ImageReader(pie_path), 0, 0,
                    width=width, height=32, preserveAspectRatio=False, mask='auto')
    except Exception as e:
        print(f"Pie de pagina no cargado: {e}")

    # ── GUARDAR ──────────────────────────────────────────────────
    c.save()
    data = buffer.getvalue()
    buffer.close()
    return data


# ═════════════════════════════════════════════════════════════════
#  HANDLER VERCEL
# ═════════════════════════════════════════════════════════════════
class handler(BaseHTTPRequestHandler):

    def set_cors_headers(self):
        self.send_header('Access-Control-Allow-Credentials', 'true')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,OPTIONS,POST,PUT')
        self.send_header('Access-Control-Allow-Headers',
                         'X-CSRF-Token, X-Requested-With, Accept, Content-Type')

    def do_OPTIONS(self):
        self.send_response(200)
        self.set_cors_headers()
        self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            data   = json.loads(self.rfile.read(length).decode('utf-8'))

            numero_convenio = data.get('numeroConvenio')
            cliente         = data.get('cliente', {})
            fecha           = data.get('fecha')
            tarifas         = data.get('tarifas')
            año_vigencia    = data.get('añoVigencia')
            tipo            = data.get('tipoHabitacion', 'hotel')  # 'hotel' | 'villas'

            if not numero_convenio or not cliente or not fecha:
                raise ValueError("Faltan datos requeridos")

            pdf_bytes  = crear_convenio_pdf(numero_convenio, cliente, fecha,
                                            tarifas=tarifas, año_vigencia=año_vigencia, tipo=tipo)
            pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')

            empresa_nombre = cliente.get('empresa', 'empresa')
            if tipo == 'villas':
                file_name = f"Convenio Villas {anio_plantilla(fecha)} ({empresa_nombre}).pdf"
            elif anio_plantilla(fecha) == '2027':
                file_name = f"Convenio Hotel 2027 ({empresa_nombre}).pdf"
            else:
                file_name = f"Convenio_({empresa_nombre}).pdf"

            try:
                tarifas_aplicadas = tarifas_para(fecha, tipo)
            except Exception:
                tarifas_aplicadas = None
            resp = {
                'anioPlantilla':  anio_plantilla(fecha),
                'tipoConvenio':   tipo,
                'tarifasAplicadas': tarifas_aplicadas,
                'success':        True,
                'message':        'Convenio generado exitosamente - Plantilla 2026',
                'numeroConvenio': numero_convenio,
                'fileName':       file_name,
                'pdfBase64':      pdf_base64,
                'cliente': {
                    'nombre':  f"{cliente.get('nombre','')} {cliente.get('apellidos','')}".strip(),
                    'empresa': cliente.get('empresa'),
                    'email':   cliente.get('email'),
                },
                'tarifas':     tarifas,
                'añoVigencia': año_vigencia,
            }

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.set_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode('utf-8'))

        except Exception as e:
            err = {'success': False, 'error': str(e),
                   'message': f'Error al generar convenio: {str(e)}'}
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.set_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps(err).encode('utf-8'))

    def do_GET(self):
        resp = {
            'status':   'active',
            'version':  'Plantilla 2026 — Columnas alineadas + Kodchasan + Americano/Buffet',
            'endpoint': '/api/generar-convenio-pdf',
        }
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.set_cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(resp).encode('utf-8'))
