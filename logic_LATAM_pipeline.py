import pandas as pd
import io
import base64
import numpy as np
import re
from datetime import datetime

def procesar_datos_json(data_list: list) -> str:
    
    # =========================================================
    # 1. CREAR DATAFRAME Y NORMALIZAR NOMBRES
    # =========================================================
    df = pd.DataFrame(data_list)
    
    # Quitamos espacios invisibles en los encabezados
    df.columns = df.columns.str.strip()

    # =========================================================
    # 2. DEFINIR COLUMNAS
    # =========================================================
    cols_trabajo = [
        "ID de registro", "Propietario del negocio", "Anual Recurring Revenue (ARR)", "AOV",
        "Costo por Transacción", "Etapa del negocio", "Fecha de creación",
        "Fecha de Ganado", "FIT o NO FIT", "Industria",
        "Monthly Fee", "Monthly GMV", "Monthly Recurring Revenue (MRR)",
        "Motivo de no fit", "Motivo de perdido", "Nombre del negocio",
        "Origen de la oportunidad (Negocio)", "Pais", "Pipeline", "SKU", "Ticket Promedio",
        "Tipo de cliente", "Transacciones Mensuales.", "Última actividad", "Valor"
    ]

    mapeo_entrada = {
        "Costo por Transacción ": "Costo por Transacción",
        "Fecha de Ganado ": "Fecha de Ganado"
    }
    df.rename(columns=mapeo_entrada, inplace=True)

    columnas_existentes = [c for c in cols_trabajo if c in df.columns]
    df = df[columnas_existentes]

    # =========================================================
    # 3. TRANSFORMACIONES ROBUSTAS
    # =========================================================
    
    # --- 3.1 LIMPIEZA DE SALTOS DE LÍNEA (Anti-Rotura de Filas) ---
    cols_texto = df.select_dtypes(include=['object']).columns
    for col in cols_texto:
        df[col] = df[col].astype(str).str.replace(r'[\r\n]+', ' ', regex=True).replace('nan', '')

    # --- 3.2 PROCESAMIENTO INTELIGENTE DE FECHAS ---
    fecha_cols = ["Fecha de creación", "Fecha de Ganado", "Última actividad"]
    
    for col in fecha_cols:
        if col in df.columns:
            # A. Primero intentamos conversión estándar (ISO strings)
            # utc=True unifica zonas horarias para evitar errores mixtos
            iso_dates = pd.to_datetime(df[col], errors='coerce', utc=True)
            
            # B. Para lo que falló (NaT), intentamos limpieza agresiva (Timestamps sucios)
            mask_nat = iso_dates.isna()
            if mask_nat.any():
                # Extraemos SOLO dígitos de la basura (ej: '0-49-16300...' -> '04916300...')
                clean_digits = df.loc[mask_nat, col].astype(str).str.replace(r'\D+', '', regex=True)
                # Convertimos a números
                numerics = pd.to_numeric(clean_digits, errors='coerce')
                
                # FILTRO DE SEGURIDAD:
                # Solo aceptamos timestamps válidos (Año 2000 a 2100 aprox)
                valid_numerics = numerics[(numerics > 946684800000) & (numerics < 4102444800000)]
                
                # Convertimos solo los válidos
                recovered_dates = pd.to_datetime(valid_numerics, unit='ms', errors='coerce', utc=True)
                iso_dates = iso_dates.fillna(recovered_dates)

            # C. Asignamos la columna limpia y quitamos hora
            df[col] = iso_dates
            # Guardamos versión string YYYY-MM-DD para exportar
            df[col + "_str"] = df[col].dt.strftime('%Y-%m-%d').replace('NaT', '')

    # --- 3.3 CONVERTIR NUMÉRICOS ---
    cols_to_int = ["Anual Recurring Revenue (ARR)", "Monthly Fee", "Monthly GMV", 
                   "Monthly Recurring Revenue (MRR)", "Transacciones Mensuales.", "Valor"]
    for col in cols_to_int:
        if col in df.columns:
            df[col] = (df[col].astype(str).str.replace(r'[$,]', '', regex=True)
                       .replace(['nan', 'None', ''], '0'))
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    # --- 3.4 CÁLCULOS DERIVADOS ---

    # Variables para cálculos de fecha
    fecha_corte = pd.Timestamp.today().normalize()
    df["Fecha de corte"] = fecha_corte.strftime('%Y-%m-%d')

    # 1. Días desde última actividad
    if "Última actividad" in df.columns:
        df["Días desde la última actividad"] = (fecha_corte.tz_localize(None) - df["Última actividad"].dt.tz_localize(None)).dt.days

    # 2. Ciclo de venta
    etapas_validas = ["7. Won", "8. In Implementation", "9. Live", "Lost", "Icebox", "Long Term"]
    ejecutivos_actuales = ["Fulano De Tal", "Jane Doe", "Pepito Perez", "John Doe"]
    
    # Normalización simple para comparar texto (quita tildes visualmente para el match)
    df["Prop_Norm"] = df["Propietario del negocio"].astype(str).str.normalize('NFKD').str.encode('ascii', errors='ignore').str.decode('utf-8')
    ejecutivos_norm = [x.encode('ascii', 'ignore').decode('utf-8') for x in ejecutivos_actuales]

    mask_ciclo = (df["Etapa del negocio"].isin(etapas_validas) & df["Prop_Norm"].isin(ejecutivos_norm))
    
    df["Duración del ciclo de venta"] = pd.NA
    if "Fecha de Ganado" in df.columns and "Fecha de creación" in df.columns:
        df.loc[mask_ciclo, "Duración del ciclo de venta"] = (
            df.loc[mask_ciclo, "Fecha de Ganado"].dt.tz_localize(None) - 
            df.loc[mask_ciclo, "Fecha de creación"].dt.tz_localize(None)
        ).dt.days

    # Limpieza final de columnas auxiliares
    df.drop(columns=["Prop_Norm"], inplace=True)
    
    # Sobreescribimos las columnas de fecha originales con la versión string bonita
    for col in fecha_cols:
        if col in df.columns:
            df[col] = df[col + "_str"]
            df.drop(columns=[col + "_str"], inplace=True)

    # Formato Enteros Nullable (para que no salga error decimal)
    cols_int_null = ["Duración del ciclo de venta", "Días desde la última actividad"]
    for col in cols_int_null:
        if col in df.columns:
            df[col] = df[col].astype("Int64")

    # =========================================================
    # 4. EXPORTACIÓN FINAL
    # =========================================================
    mapeo_salida = {
        "Costo por Transacción ": "Costo por Transacción",
        "Fecha de Ganado ": "Fecha de Ganado"
    }
    df.rename(columns=mapeo_salida, inplace=True)

    output_buffer = io.StringIO()
    df.to_csv(output_buffer, index=False, encoding="utf-8-sig", quoting=1) 
    output_buffer.seek(0)
    
    encoded_output = base64.b64encode(output_buffer.getvalue().encode("utf-8-sig")).decode("utf-8")

    return encoded_output