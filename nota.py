import os
import sys
import json
import base64
import hashlib
import zipfile
import re
import requests
import threading
import tkinter as tk
import customtkinter as ctk
from tkinter import messagebox, filedialog, simpledialog

# ===========================================================
# CONFIGURACIÓN VISUAL Y TIPOGRAFÍA (DISEÑO MODERNO)
# ===========================================================
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Paleta de colores profesionales (Estilo VS Code / Tailwind Slate)
C_BG = "#0f172a"
C_PANEL = "#1e293b"
C_CARD = "#334155"
C_PRIMARY = "#0ea5e9"
C_SUCCESS = "#10b981"
C_DANGER = "#ef4444"
C_TEXT = "#f8fafc"
C_MUTED = "#94a3b8"

FUENTE_TITULO = ("Segoe UI", 16, "bold")
FUENTE_SUBTITULO = ("Segoe UI", 13, "bold")
FUENTE_TEXTO = ("Segoe UI", 12)
FUENTE_CHICA = ("Segoe UI", 11)

# Detectar si estamos en un ejecutable empaquetado o en código fuente
if getattr(sys, 'frozen', False):
    # Si es el .exe, el directorio real es donde está el propio ejecutable
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # Si es script de python, es donde está el script
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# =========================================================
# Class ToolTip: para agregar mensajes emergentes a cualquier widget de Tkinter
# =========================================================
class ToolTip:
    def __init__(self, widget, text, delay=600):
        self.widget = widget
        self.text = text
        self.delay = delay  # Tiempo en milisegundos (600ms = 0.6 segundos)
        self.tooltip_window = None
        self.timer_id = None
        
        try:
            self.widget.bind("<Enter>", self.al_entrar)
            self.widget.bind("<Leave>", self.al_salir)
            self.widget.bind("<ButtonPress>", self.al_salir)
        except NotImplementedError:
            # Si el widget (como CTkSegmentedButton) bloquea el .bind(),
            # lo vinculamos directamente a su lienzo (_canvas) interno.
            if hasattr(self.widget, "_canvas"):
                self.widget._canvas.bind("<Enter>", self.al_entrar)
                self.widget._canvas.bind("<Leave>", self.al_salir)
                self.widget._canvas.bind("<ButtonPress>", self.al_salir)

    def al_entrar(self, event=None):
        self.cancelar_temporizador() # Asegura que no haya duplicados
        # Programa la aparición de la ventana después de 'delay' milisegundos
        self.timer_id = self.widget.after(self.delay, self.mostrar_tooltip)

    def al_salir(self, event=None):
        self.cancelar_temporizador()
        self.ocultar_tooltip()

    def cancelar_temporizador(self):
        if self.timer_id:
            self.widget.after_cancel(self.timer_id)
            self.timer_id = None

    def mostrar_tooltip(self):
        if self.tooltip_window:
            return
            
        self.tooltip_window = tk.Toplevel(self.widget)
        self.tooltip_window.wm_overrideredirect(True)
        
        # 1. TRUCO DE TRANSPARENCIA MEJORADO
        # Usamos un negro casi puro ("#000001") en lugar de magenta para 
        # que el suavizado de bordes se funda con el tema oscuro sin dejar rastro.
        color_invisible = "#000001"
        self.tooltip_window.configure(bg=color_invisible)
        self.tooltip_window.wm_attributes("-transparentcolor", color_invisible)

        # NUEVO: Controla la transparencia general del ToolTip (ej. 0.9 = 90% sólido)
        self.tooltip_window.wm_attributes("-alpha", 0.85)

        # 2. CONTENEDOR CON BORDES REDONDEADOS
        frame_tooltip = ctk.CTkFrame(self.tooltip_window, 
                                     fg_color="#1e293b",       
                                     corner_radius=10,         
                                     border_width=1,           
                                     border_color="#3b82f6")   
        frame_tooltip.pack(padx=2, pady=2) 

        # 3. TEXTO
        label = ctk.CTkLabel(frame_tooltip, 
                             text=self.text, 
                             text_color="white",
                             fg_color="transparent",
                             font=("Segoe UI", 12),
                             wraplength=250, 
                             justify="left")
        label.pack(padx=12, pady=8)

        # 4. OBTENER TAMAÑO SOLICITADO
        self.tooltip_window.update_idletasks() 
        ancho_tooltip = frame_tooltip.winfo_reqwidth()
        alto_tooltip = frame_tooltip.winfo_reqheight()
        
        ancho_pantalla = self.widget.winfo_screenwidth()
        alto_pantalla = self.widget.winfo_screenheight()
        
        # 5. POSICIÓN (Centrado y ABAJO del componente)
        x = int(self.widget.winfo_rootx() + (self.widget.winfo_width() / 2) - (ancho_tooltip / 2))
        y = int(self.widget.winfo_rooty() + self.widget.winfo_height() + 10)
        
        # 6. CORRECCIÓN DE BORDES
        # Evitar que se salga por los lados
        if x < 0:
            x = 10
        elif (x + ancho_tooltip) > ancho_pantalla:
            x = ancho_pantalla - ancho_tooltip - 10
            
        # Evitar que se salga por abajo (si topa abajo, lo pasa para arriba)
        if (y + alto_tooltip) > alto_pantalla: 
            y = int(self.widget.winfo_rooty() - alto_tooltip - 10)
            
        self.tooltip_window.wm_geometry(f"+{x}+{y}")
    
    def ocultar_tooltip(self):
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None


# ===========================================================
# CLASE ÚNICA: TODA LA LÓGICA DE NEGOCIO (INTACTA)
# ===========================================================
class NotaInstalacionManager:
    ALIAS_PUESTO = ["puesto", "cargo", "rol", "posicion", "posición"]
    CATEGORIAS_ORDEN = ["Líder de Proyecto", "Arquitecto", "Desarrollador", "Analista de Casos de Pruebas"]

    def __init__(self, config_path=CONFIG_PATH):
        self.config_path = config_path
        self.organization = None
        self.pat = None
        self._headers = None
        self._data_cache = {"personas": [], "equipos": {}, "azure": {}}
        self._cargar_config()

    def _cargar_config(self):
        if not os.path.exists(self.config_path): return
        try:
            with open(self.config_path, "r", encoding="utf-8") as f: 
                data = json.load(f)
        except json.JSONDecodeError:
            print("El archivo config.json está corrupto. Cargando configuración por defecto.")
            data = {"personas": [], "equipos": {}, "azure": {}}

        data.setdefault("personas", [])
        data.setdefault("equipos", {})
        data.setdefault("azure", {})
        data["azure"].setdefault("proyectos", [])
        data["azure"].setdefault("proyectos_nota", [])
        self._data_cache = data
        azure_cfg = data.get("azure", {})
        self.organization = azure_cfg.get("organization")
        self.pat = azure_cfg.get("pat")
        if self.pat:
            auth_str = base64.b64encode(f":{self.pat}".encode()).decode()
            self._headers = {"Authorization": f"Basic {auth_str}", "Content-Type": "application/json"}

    def guardar_config(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self._data_cache, f, indent=4, ensure_ascii=False)

    def validar_config(self):
        problemas = []
        if not os.path.exists(self.config_path): problemas.append(f"No se encontró el archivo '{self.config_path}'.")
        elif not self._data_cache.get("personas"): problemas.append("El JSON no tiene personas registradas en 'personas'.")
        if not self._data_cache.get("azure", {}).get("organization"): problemas.append("Falta 'organization' dentro de la clave 'azure'.")
        if not self._data_cache.get("azure", {}).get("pat"): problemas.append("Falta 'pat' dentro de la clave 'azure'.")
        return problemas

    def listar_proyectos_configurados(self):
        """Devuelve la lista de proyectos o una lista vacía si no existe, evitando KeyError."""
        # Obtenemos la sección azure de forma segura
        azure_data = self._data_cache.get("azure", {})
        
        # Obtenemos la lista de proyectos de forma segura
        return azure_data.get("proyectos", [])

    def listar_proyectos_nota_configurados(self): 
        return self._data_cache.get("azure", {}).get("proyectos_nota", [])
    
    def agregar_proyecto(self, tipo, nombre):
        clave = "proyectos" if tipo == "azure" else "proyectos_nota"
        
        # Inicialización segura
        if "azure" not in self._data_cache:
            self._data_cache["azure"] = {}
        if clave not in self._data_cache["azure"]:
            self._data_cache["azure"][clave] = []
            
        if nombre not in self._data_cache["azure"][clave]:
            self._data_cache["azure"][clave].append(nombre)
            self.guardar_config()

    def eliminar_proyecto(self, tipo, nombre):
        clave = "proyectos" if tipo == "azure" else "proyectos_nota"
        
        # Extracción segura
        lista_proyectos = self._data_cache.get("azure", {}).get(clave, [])
        if nombre in lista_proyectos:
            lista_proyectos.remove(nombre)
            self._data_cache["azure"][clave] = lista_proyectos
            self.guardar_config()

    def _validar_listo_azure(self):
        if not self.organization or not self.pat or not self._headers: raise ValueError(f"Faltan credenciales de Azure DevOps en '{self.config_path}'")

    def _get(self, url, params=None):
        self._validar_listo_azure()
        resp = requests.get(url, headers=self._headers, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def obtener_release(self, project, release_id):
        return self._get(f"https://vsrm.dev.azure.com/{self.organization}/{project}/_apis/release/releases/{release_id}", params={"api-version": "7.1"})

    def listar_releases(self, project, definition_id=None, top=30, search_text=None):
        params = {"api-version": "7.1", "$top": top, "queryOrder": "descending"}
        if definition_id: params["definitionId"] = definition_id
        if search_text: params["searchText"] = search_text
        return self._get(f"https://vsrm.dev.azure.com/{self.organization}/{project}/_apis/release/releases", params=params).get("value", [])

    def listar_definiciones_release(self, project, search_text=None, top=200):
        definiciones = self._get(f"https://vsrm.dev.azure.com/{self.organization}/{project}/_apis/release/definitions", params={"api-version": "7.1", "$top": top}).get("value", [])
        if search_text: definiciones = [d for d in definiciones if search_text.lower() in d.get("name", "").lower()]
        return definiciones

    def obtener_build(self, project, build_id):
        return self._get(f"https://dev.azure.com/{self.organization}/{project}/_apis/build/builds/{build_id}", params={"api-version": "7.1"})

    def obtener_pull_request_por_id(self, project, pr_id):
        return self._get(f"https://dev.azure.com/{self.organization}/_apis/git/pullrequests/{pr_id}", params={"api-version": "7.1"})

    def buscar_tag_en_build_tags(self, build_info):
        patron = re.compile(r"^v?\d+\.\d+\.\d+$", re.IGNORECASE)
        for tag in (build_info.get("tags", []) or []):
            if patron.match(tag.strip()): return tag.strip().lstrip("vV")
        return ""

    def obtener_tags_del_repositorio(self, repository_id):
        return self._get(f"https://dev.azure.com/{self.organization}/_apis/git/repositories/{repository_id}/refs", params={"api-version": "7.1", "filter": "tags"}).get("value", [])

    def resolver_commit_de_tag_anotado(self, repository_id, object_id):
        try: return (self._get(f"https://dev.azure.com/{self.organization}/_apis/git/repositories/{repository_id}/annotatedtags/{object_id}", params={"api-version": "7.1"}).get("taggedObject", {}) or {}).get("objectId", "")
        except requests.HTTPError: return ""

    def buscar_tag_para_commit(self, repository_id, commit_sha):
        if not repository_id or not commit_sha: return ""
        try: tags = self.obtener_tags_del_repositorio(repository_id)
        except Exception: return ""
        for tag in tags:
            object_id = tag.get("objectId", "")
            commit_real = self.resolver_commit_de_tag_anotado(repository_id, object_id) or object_id if object_id != commit_sha else object_id
            if commit_real == commit_sha: return tag.get("name", "").replace("refs/tags/", "").lstrip("vV")
        return ""

    def buscar_tag_en_variables(self, release):
        candidatos = ["tagversion", "tag_version", "version", "tag"]
        for key, val in (release.get("variables", {}) or {}).items():
            if key.lower() in candidatos and (val or {}).get("value", ""): return val["value"]
        for env in release.get("environments", []) or []:
            for key, val in (env.get("variables", {}) or {}).items():
                if key.lower() in candidatos and (val or {}).get("value", ""): return val["value"]
        return ""

    def obtener_timeline_build(self, project, build_id):
        return self._get(f"https://dev.azure.com/{self.organization}/{project}/_apis/build/builds/{build_id}/timeline", params={"api-version": "7.1"})

    def obtener_log_texto(self, project, build_id, log_id):
        self._validar_listo_azure()
        resp = requests.get(f"https://dev.azure.com/{self.organization}/{project}/_apis/build/builds/{build_id}/logs/{log_id}", headers=self._headers, params={"api-version": "7.1"}, timeout=30)
        resp.raise_for_status()
        return resp.text

    def buscar_tag_en_logs_de_push(self, project, build_id, componente=None, palabras_clave=None):
        palabras_clave = palabras_clave or ["push image", "push", "docker"]
        try: timeline = self.obtener_timeline_build(project, build_id)
        except Exception: return "", ""
        registros = timeline.get("records", []) or []
        candidatos = [r for r in registros if r.get("log") and "push" in r.get("name", "").lower() and "image" in r.get("name", "").lower()]
        if not candidatos: candidatos = [r for r in registros if r.get("log") and any(k in r.get("name", "").lower() for k in palabras_clave)]
        patron_esp = re.compile(rf"{re.escape(componente)}:(\d+\.\d+\.\d+)") if componente else None
        patron_gen = re.compile(r"[/:](\d+\.\d+\.\d+)(?:\s|$)")
        for r in candidatos:
            log_id = r.get("log", {}).get("id")
            if not log_id: continue
            try: contenido = self.obtener_log_texto(project, build_id, log_id)
            except Exception: continue
            if patron_esp:
                match = patron_esp.search(contenido)
                if match: return match.group(1), r.get("name", "")
            match = patron_gen.search(contenido)
            if match: return match.group(1), r.get("name", "")
        return "", ""

    def obtener_tag_version_sugerido(self, release, project, repository_id, commit_sha, build_info=None, build_id=None, componente=None):
        if build_id:
            tag, step = self.buscar_tag_en_logs_de_push(project, build_id, componente=componente)
            if tag: return tag, f"log del step '{step}'"
        tag = self.buscar_tag_para_commit(repository_id, commit_sha)
        if tag: return tag, "git tag"
        tag = self.buscar_tag_en_variables(release)
        if tag: return tag, "variables"
        tag = self.buscar_tag_en_build_tags(build_info or {})
        if tag: return tag, "build tag"
        return "", "no encontrado"

    def buscar_commit_en_repo_central(self, project, nombre_repo, carpeta):
        """Busca el commit de una carpeta y forza el Merge Commit si viene de un PR para coincidencia visual."""
        if not carpeta: 
            return "", "El nombre de la carpeta (componente) está vacío."
        
        # 1. Búsqueda del commit original (el que modificó los archivos)
        url_commit = f"https://dev.azure.com/{self.organization}/{project}/_apis/git/repositories/{nombre_repo}/commits"
        params_commit = {
            "searchCriteria.itemPath": f"/{carpeta}",
            "searchCriteria.itemVersion.version": "master",
            "searchCriteria.itemVersion.versionType": "branch",
            "$top": 1,
            "api-version": "7.1"
        }
        
        try:
            resp = self._get(url_commit, params=params_commit)
            commits = resp.get("value", [])
            
            if commits:
                commit_original = commits[0].get("commitId", "")
                
                # 2. RUTA DOBLE: Preguntar a Azure si este commit pertenece a un Pull Request
                url_pr = f"https://dev.azure.com/{self.organization}/{project}/_apis/git/repositories/{nombre_repo}/commits/{commit_original}/pullRequests"
                try:
                    prs = self._get(url_pr, params={"api-version": "7.1"}).get("value", [])
                    if prs:
                        # Si existe un PR, extraemos el Merge Commit (el que se ve en la web)
                        merge_commit = (prs[0].get("lastMergeCommit", {}) or {}).get("commitId", "")
                        if merge_commit:
                            return merge_commit, ""
                except Exception:
                    pass # Si ocurre un error en esta segunda búsqueda, ignoramos silenciosamente
                
                # Si el código llega aquí, significa que NO vino de un PR (se subió directo a master) 
                # o la búsqueda del PR falló. Devolvemos el original como respaldo seguro.
                return commit_original, ""
            else:
                return "", f"No se encontró historial para '/{carpeta}' en la rama master."
                
        except Exception as e:
            return "", f"Error al buscar historial de '/{carpeta}': {e}"

    def _armar_info_desde_release(self, release, project, artifact_alias=None):
        warnings = []
        release_id = release.get("id")
        artifacts = release.get("artifacts", [])
        
        if not artifacts: 
            warnings.append("El release no tiene artifacts asociados.")
            artifact = {}
        else:
            artifact = artifacts[0] if not artifact_alias else next((a for a in artifacts if a.get("alias") == artifact_alias), artifacts[0])
            
        def_ref = artifact.get("definitionReference", {}) or {}
        art_type = artifact.get("type", "")
        
        build_id = ""
        build_number = ""
        build_info = {}
        commit = ""
        rama = ""
        repo_name = ""
        repo_id_real = ""
        
        # --- LÓGICA INTELIGENTE SEGÚN EL TIPO DE ARTEFACTO ---
        if art_type == "Build":
            build_id = (def_ref.get("version", {}) or {}).get("id")
            build_number = (def_ref.get("version", {}) or {}).get("name")
            if build_id:
                try: 
                    build_info = self.obtener_build(project, build_id)
                    commit = build_info.get("sourceVersion", "")
                    rama = (build_info.get("sourceBranch", "")).replace("refs/heads/", "")
                    repo_info = build_info.get("repository", {}) or {}
                    repo_name = repo_info.get("name", "")
                    repo_id_real = repo_info.get("id", "")
                except Exception: 
                    warnings.append(f"No se pudo cargar el historial del build {build_id}.")
            
            # Respaldos por si la API de build falla
            if not rama: rama = (def_ref.get("branch", {}) or {}).get("name", "").replace("refs/heads/", "")
            if not repo_name: repo_name = (def_ref.get("repository", {}) or {}).get("name", "")
                
        elif art_type == "Git":
            # Si el artefacto viene directo de un repositorio Git
            commit = (def_ref.get("version", {}) or {}).get("id", "")
            rama = (def_ref.get("branch", {}) or {}).get("name", "").replace("refs/heads/", "")
            repo_info = def_ref.get("repository", {}) or {}
            repo_name = repo_info.get("name", "")
            repo_id_real = repo_info.get("id", "")
            # Usamos los primeros 8 caracteres del commit como número de build simulado
            build_number = commit[:8] if commit else "N/A"
            
        else:
            warnings.append(f"Tipo de artefacto desconocido o no soportado: {art_type}")
            repo_name = (def_ref.get("repository", {}) or {}).get("name", "")
        # -----------------------------------------------------

        pr_number = str((build_info.get("triggerInfo", {}) or {}).get("pr.number", "") or "")
        if pr_number:
            try:
                pr_data = self.obtener_pull_request_por_id(project, pr_number)
                repo_pr = pr_data.get("repository", {}) or {}
                if repo_pr.get("name"): repo_name = repo_pr.get("name")
                if repo_pr.get("id"): repo_id_real = repo_pr.get("id")
                if pr_data.get("targetRefName"): rama = pr_data.get("targetRefName", "").replace("refs/heads/", "")
                if (pr_data.get("lastMergeCommit", {}) or {}).get("commitId"): commit = pr_data["lastMergeCommit"]["commitId"]
            except Exception: 
                warnings.append(f"No se pudo cargar la información del PR #{pr_number}.")

        # Búsqueda en Properties
        commit_prop = ""
        url_prop = ""
        commit_env = ""
        url_env = ""
        
        if repo_name:
            commit_prop, err_prop = self.buscar_commit_en_repo_central(project, "properties", repo_name)
            if err_prop: warnings.append(err_prop)
            url_prop = f"https://dev.azure.com/{self.organization}/{project}/_git/properties?path=%2F{repo_name}&version=GBmaster" if commit_prop else ""
            
            ruta_env = f"{repo_name}/environment.ts"
            commit_env, _ = self.buscar_commit_en_repo_central(project, "properties", ruta_env)
            url_env = f"https://dev.azure.com/{self.organization}/{project}/_git/properties?path=%2F{repo_name}%2Fenvironment.ts&version=GBmaster" if commit_env else ""
        else:
            warnings.append("No se buscó en 'properties' porque no se detectó el nombre del componente.")

        info = {
            "organizacion": "Coppel", "proyecto": project, "componente": repo_name,
            "rama": rama, "version_build": build_number,
            "nombre_release": release.get("releaseDefinition", {}).get("name", ""),
            "release": release.get("name", ""),
            "url_release": f"https://dev.azure.com/{self.organization}/{project}/_releaseProgress?_a=release-pipeline-progress&releaseId={release_id}",
            "commit_release": commit,
            "url_repositorio": f"https://dev.azure.com/{self.organization}/{project}/_git/{repo_name}" if repo_name else "",
            "pr_number": pr_number, "_warnings": warnings,
            "pr_a_master": f"https://dev.azure.com/{self.organization}/{project}/_git/{repo_name}/pullrequest/{pr_number}" if pr_number and repo_name else "",
            "commit_properties": commit_prop,
            "url_properties": url_prop,
            "commit_environment": commit_env,
            "url_environment": url_env
        }
        
        tag_sug, org_tag = self.obtener_tag_version_sugerido(release, project, repo_id_real, commit, build_info, build_id, componente=repo_name)
        info["tag_version_sugerido"] = tag_sug
        info["_build_id_para_tag"] = build_id
        return info

    def obtener_info_componente(self, project, release_id): return self._armar_info_desde_release(self.obtener_release(project, release_id), project)

    def calcular_md5(self, ruta):
        h = hashlib.md5()
        with open(ruta, "rb") as f:
            for c in iter(lambda: f.read(8192), b""): h.update(c)
        return h.hexdigest()

    def extraer_componentes_de_zip(self, ruta):
        blacklist = [".odt", ".doc", ".sh"]
        res = []
        with zipfile.ZipFile(ruta, "r") as z:
            for entry in z.infolist():
                nombre = os.path.basename(entry.filename)
                # Validamos que no sea carpeta, que tenga nombre y que la extensión no esté bloqueada
                if not entry.is_dir() and nombre:
                    ext = os.path.splitext(nombre)[1].lower()
                    if ext not in blacklist:
                        res.append({"nombre": nombre, "md5": hashlib.md5(z.read(entry.filename)).hexdigest()})
        return res

    def _obtener_puesto(self, p): return next((p[k] for k in self.ALIAS_PUESTO if k in p and p[k]), "Sin puesto")
    def _clasificar_puesto(self, p):
        p = (p or "").lower()
        if "líder" in p or "lider" in p: return "Líder de Proyecto"
        if "arquitect" in p: return "Arquitecto"
        if "desarroll" in p: return "Desarrollador"
        if "analista" in p: return "Analista de Casos de Pruebas"
        return "Otros"
    def _orden_categoria_key(self, p):
        c = self._clasificar_puesto(self._obtener_puesto(p))
        return self.CATEGORIAS_ORDEN.index(c) if c in self.CATEGORIAS_ORDEN else len(self.CATEGORIAS_ORDEN)
    def listar_nombres_equipos(self): return list(self._data_cache.get("equipos", {}).keys())

    def obtener_escalamiento(self, emails=None):
        personas = self._data_cache.get("personas", [])
        if emails: personas = [p for p in personas if p.get("email") in emails]
        return [{"puesto": self._obtener_puesto(p), "nombre": p.get("nombre", "N/A"), "telefono": p.get("telefono", "N/A"), "email": p.get("email", "N/A")} for p in sorted(personas, key=self._orden_categoria_key)]

    def obtener_escalamiento_de_equipo(self, n_equipo):
        analista_cp = self._data_cache.get("analista_email", "")
        integrantes = self._data_cache.get("equipos", {}).get(n_equipo) 
        if not integrantes: raise ValueError(f"No existe el equipo '{n_equipo}'.")
        personas = self._data_cache.get("personas", [])
        integrantes.append({"email": analista_cp, "puesto": "Analista de Casos de Pruebas"})
        res = []
        for e in integrantes:
            email = e.get("email") if isinstance(e, dict) else e
            ov = e.get("puesto") if isinstance(e, dict) else None
            cands = [p for p in personas if p.get("email") == email]
            if cands:
                eleg = dict(cands[0])
                if ov: eleg["puesto"] = ov
                res.append(eleg)
        return [{"puesto": self._obtener_puesto(p), "nombre": p.get("nombre", "N/A"), "telefono": p.get("telefono", "N/A"), "email": p.get("email", "N/A")} for p in sorted(res, key=self._orden_categoria_key)]

    def bloque_componentes_manual(self, componentes):
        partes = ["Favor de Instalar en el siguiente orden"]
        for i, c in enumerate(componentes, start=1):
            ip, bd, drive = (c.get("ip") or "").strip(), (c.get("bd") or "").strip(), (c.get("drive") or "").strip()
            if ip or bd:
                partes.append(f"{i}.- Se instalará en:")
                if ip: partes.append(f"IP: {ip}")
                if bd: partes.append(f"BD: {bd}")
                partes.append("El siguiente componente:")
            else:
                partes.append(f"{i}.- Instalar el siguiente componente:")
            partes.extend([f"Componente: {c['nombre']}", f"MD5: {c['md5']}", f"Drive: {drive}"])
            if drive: partes.append(f"Drive: {drive}")
            partes.append("")
        return "\n".join(partes).rstrip()

    def bloque_rollback_manual(self, z_nom, z_md5, z_drv, comps=None):
        partes = ["Rollback:", z_nom, f"MD5: {z_md5}",f"Drive: {z_drv or ''}"]
        if comps: partes.extend(["", f"En caso de requerir un rollback, deberá descomprimirse el archivo {z_nom} y proceder con la instalación de los siguientes componentes en el orden que se detalla a continuación:", "", self.bloque_componentes_manual(comps)])
        return "\n".join(partes)

    def bloque_escalamiento(self, personas):
        if not personas: return ""
        partes = ["Datos de escalamiento:"]
        for p in personas: partes.extend([f"{p['puesto']}: {p['nombre']}", f"Teléfono: {p['telefono']}", f"Email: {p['email']}", ""])
        return "\n".join(partes).rstrip()

    def bloque_rutas_repositorio(self, componentes, rollback_zip=None):
        lineas = ["Ruta repositorio de código:\n"]
        
        # Agrega las rutas de todos los componentes principales (estén vacías o no)
        for c in componentes:
            lineas.append(c["nombre"])
            lineas.append(f"Ruta de drive: {c.get('drive', '')}")
            lineas.append(f"Ruta de Azure: {c.get('azure', '')}")
            lineas.append("") # Salto de línea visual
            
        # Agrega las rutas del ZIP de rollback principal si existe
        if rollback_zip:
            lineas.append(rollback_zip["nombre"])
            lineas.append(f"Ruta de drive: {rollback_zip.get('drive', '')}")
            lineas.append(f"Ruta azure: {rollback_zip.get('azure', '')}")
            lineas.append("")
            
        return "\n".join(lineas).rstrip()

    def armar_nota_manual(self, componentes, excepto="N/A", rollback_zip=None, equipo_escalamiento=None, incluir_escalamiento=True):
        partes = [self.bloque_componentes_manual(componentes), f"Excepto a:\n{excepto}"]
        
        if rollback_zip: 
            partes.append(self.bloque_rollback_manual(rollback_zip["nombre"], rollback_zip["md5"], rollback_zip["drive"], rollback_zip.get("componentes", [])))  
        
        
        if incluir_escalamiento: 
            partes.append(self.bloque_escalamiento(self.obtener_escalamiento_de_equipo(equipo_escalamiento) if equipo_escalamiento and equipo_escalamiento != "-- Todas las personas --" else self.obtener_escalamiento()))
            
        # --- SE INYECTA EL BLOQUE DE RUTAS (Siempre visible) ---
        partes.append(self.bloque_rutas_repositorio(componentes, rollback_zip))
        return "\n\n".join(partes)

    def bloque_azure_componente(self, info, variables=None, tag_version="", commit_properties="", url_properties="", commit_environment="", url_environment=""):
        lineas = ["-" * 55, "", f"Organización: {info.get('organizacion', 'Coppel')}", f"Proyecto: {info['proyecto']}", f"Componente: {info['componente']}", f"RAMA: {info['rama']}", f"Versión Build: {info['version_build']}", f"Nombre del Release: {info['nombre_release']}", f"Release: {info['release']}", f"URL Release: {info['url_release']}", f"Commit Release: {info['commit_release']}", f"URL Repositorio: {info['url_repositorio']}"]
        if commit_properties: lineas.append(f"Commit properties: {commit_properties}")
        if url_properties: lineas.append(f"URL properties: {url_properties}")
        if commit_environment: lineas.append(f"Commit environment.ts: {commit_environment}")
        if url_environment: lineas.append(f"Url environment.ts: {url_environment}")
        if tag_version: lineas.append(f"Tag version: {tag_version}")
        if info.get("pr_a_master"): lineas.append(f"PR a Master: {info['pr_a_master']}")
        if variables:
            lineas.append("Variables:")
            for k, v in variables.items(): lineas.append(f"{k} : {v}")
        return "\n".join(lineas)

    def bloque_backup_sre(self, componente, pasos, proyecto="cpl-corp-cial-prod-17042024", cluster="gke-corp-cial-prod-01"):
        partes = ["IMPORTANTE!!!", "Favor de realizar el backup: - tarea de SRE", "PROCESO OBLIGATORIO BACKUP: REALIZAR ESTA ACTIVIDAD PARA EL SIGUIENTE SERVICIO !!!", f"Proyecto: {proyecto}", f"Cluster:{cluster}", f"Componente: {componente}"]
        partes.extend([f"{i}. {p}" for i, p in enumerate(pasos, 1)])
        return "\n".join(partes)

    def armar_nota_azure(self, bloques_componentes, excepto="N/A", rollback_bloques=None, backup_texto="", equipo_escalamiento=None):
        partes = ["\n\n".join(bloques_componentes), f"Excepto a:\n{excepto}"]
        if rollback_bloques: partes.append("Rollback:\n" + "\n\n".join(rollback_bloques))
        if backup_texto: partes.append(backup_texto)
        partes.append(self.bloque_escalamiento(self.obtener_escalamiento_de_equipo(equipo_escalamiento) if equipo_escalamiento and equipo_escalamiento != "-- Todas las personas --" else self.obtener_escalamiento()))
        return "\n\n".join(partes)

# ===========================================================
# DIÁLOGO DE BÚSQUEDA
# ===========================================================
class PipelineReleaseSearchDialog(ctk.CTkToplevel):
    def __init__(self, master, manager, organization, project, on_seleccionar):
        super().__init__(master)
        self.title("Buscar Componente Azure")
        self.geometry("600x480")
        self.manager, self.organization, self.project, self.on_seleccionar = manager, organization, project, on_seleccionar
        self.transient(master)
        self.grab_set()
        self.manager.organization = self.organization

        self.frame_paso1 = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_paso1.pack(fill="both", expand=True, padx=15, pady=15)
        top1 = ctk.CTkFrame(self.frame_paso1, fg_color="transparent")
        top1.pack(fill="x", pady=(0, 10))
        self.entry_componente = ctk.CTkEntry(top1, placeholder_text="Nombre del componente", font=FUENTE_TEXTO, height=35)
        self.entry_componente.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.entry_componente.bind("<Return>", lambda e: self._buscar_pipelines())
        ctk.CTkButton(top1, text="Buscar", font=FUENTE_TEXTO, height=35, fg_color=C_PRIMARY, command=self._buscar_pipelines).pack(side="left")

        self.resultados_pipelines = ctk.CTkScrollableFrame(self.frame_paso1, fg_color=C_PANEL, corner_radius=10)
        self.resultados_pipelines.pack(fill="both", expand=True)

        self.frame_paso2 = ctk.CTkFrame(self, fg_color="transparent")
        top2 = ctk.CTkFrame(self.frame_paso2, fg_color="transparent")
        top2.pack(fill="x", padx=15, pady=(15, 5))
        ctk.CTkButton(top2, text="⬅ Volver", font=FUENTE_TEXTO, width=100, fg_color=C_CARD, command=self._volver_a_paso1).pack(side="left")
        self.lbl_pipeline_actual = ctk.CTkLabel(top2, text="", font=FUENTE_SUBTITULO, text_color=C_PRIMARY)
        self.lbl_pipeline_actual.pack(side="left", padx=15)

        self.resultados_releases = ctk.CTkScrollableFrame(self.frame_paso2, fg_color=C_PANEL, corner_radius=10)
        self.resultados_releases.pack(fill="both", expand=True, padx=15, pady=(0, 15))

    def _buscar_pipelines(self):
        for w in self.resultados_pipelines.winfo_children(): w.destroy()
        texto = self.entry_componente.get().strip()
        if not texto: return
        try:
            definiciones = self.manager.listar_definiciones_release(self.project, search_text=texto)
            for d in definiciones:
                fila = ctk.CTkFrame(self.resultados_pipelines, fg_color=C_CARD, corner_radius=8)
                fila.pack(fill="x", padx=5, pady=4)
                ctk.CTkLabel(fila, text=d.get('name'), font=FUENTE_TEXTO).pack(side="left", padx=10, pady=10)
                ctk.CTkButton(fila, text="Ver releases", font=FUENTE_TEXTO, fg_color=C_PRIMARY, command=lambda dd=d: self._mostrar_releases(dd)).pack(side="right", padx=10, pady=10)
        except Exception as e: ctk.CTkLabel(self.resultados_pipelines, text=f"Error: {e}", text_color=C_DANGER).pack()

    def _mostrar_releases(self, definicion):
        self.lbl_pipeline_actual.configure(text=f"📦 {definicion.get('name')}")
        self.frame_paso1.pack_forget()
        self.frame_paso2.pack(fill="both", expand=True)
        self._cargar_releases(definicion.get("id"))

    def _volver_a_paso1(self):
        self.frame_paso2.pack_forget()
        self.frame_paso1.pack(fill="both", expand=True, padx=15, pady=15)

    def _cargar_releases(self, definition_id):
        for w in self.resultados_releases.winfo_children(): w.destroy()
        try:
            releases = self.manager.listar_releases(self.project, definition_id=definition_id, top=30)
            for rel in releases:
                fila = ctk.CTkFrame(self.resultados_releases, fg_color=C_CARD, corner_radius=8)
                fila.pack(fill="x", padx=5, pady=4)
                ctk.CTkLabel(fila, text=f"{rel.get('name')} - Creado: {rel.get('createdOn', '')[:10]}", font=FUENTE_TEXTO).pack(side="left", padx=10, pady=10)
                ctk.CTkButton(fila, text="Seleccionar", font=FUENTE_TEXTO, fg_color=C_SUCCESS, command=lambda r=rel: self._seleccionar(r)).pack(side="right", padx=10, pady=10)
        except Exception as e: ctk.CTkLabel(self.resultados_releases, text=f"Error: {e}", text_color=C_DANGER).pack()

    def _seleccionar(self, release):
        self.on_seleccionar(release)
        self.destroy()

# ===========================================================
# DIÁLOGO PERSONALIZADO PARA TOKEN AZURE
# ===========================================================
class DialogoTokenAzure(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Configuración de Azure")
        self.geometry("500x220")
        self.resizable(False, False)
        self.configure(fg_color=C_BG)
        self.valor = None
        
        # Bloquear la ventana principal hasta que se cierre esta
        self.transient(master)
        self.grab_set()

        # Centrar la ventanita respecto a la PANTALLA completa
        self.update_idletasks()
        ancho_pantalla = self.winfo_screenwidth()
        alto_pantalla = self.winfo_screenheight()
        
        x = (ancho_pantalla // 2) - (500 // 2)
        y = (alto_pantalla // 2) - (220 // 2)
        self.geometry(f"+{x}+{y}")

        # Diseño UI
        ctk.CTkLabel(self, text="No se detectó el Token (PAT) de Azure", font=FUENTE_TITULO, text_color=C_PRIMARY).pack(pady=(25, 5))
        ctk.CTkLabel(self, text="Por favor, ingresa tu token para guardarlo en la configuración:", font=FUENTE_TEXTO, text_color=C_TEXT).pack(pady=(0, 15))

        # NUEVO: Se agregó show="*" para ocultar el token por seguridad
        self.entry_token = ctk.CTkEntry(self, placeholder_text="Pega tu Personal Access Token (PAT) aquí...", font=FUENTE_TEXTO, width=420, height=35, show="*")
        self.entry_token.pack(pady=(0, 20))

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack()

        ctk.CTkButton(btn_frame, text="💾 Guardar Token", font=FUENTE_SUBTITULO, width=140, height=38, fg_color=C_SUCCESS, hover_color="#059669", command=self._guardar).pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="Cancelar", font=FUENTE_SUBTITULO, width=100, height=38, fg_color=C_CARD, hover_color="#dc2626", command=self._cancelar).pack(side="left", padx=10)

    def _guardar(self):
        self.valor = self.entry_token.get()
        self.destroy()

    def _cancelar(self):
        self.valor = None
        self.destroy()

    def get_input(self):
        # Pausa la ejecución hasta que la ventana se destruya
        self.master.wait_window(self)
        return self.valor

# ===========================================================
# DIÁLOGO PERSONALIZADO PARA ENTRADAS DE TEXTO
# ===========================================================
class DialogoEntradaTexto(ctk.CTkToplevel):
    def __init__(self, master, titulo, mensaje):
        super().__init__(master)
        self.title(titulo)
        self.geometry("400x200")
        self.resizable(False, False)
        self.configure(fg_color=C_BG)
        self.valor = None
        
        self.transient(master)
        self.grab_set()

        # Centrar la ventanita
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (400 // 2)
        y = (self.winfo_screenheight() // 2) - (200 // 2)
        self.geometry(f"+{x}+{y}")

        # Diseño UI acorde a tu tema
        ctk.CTkLabel(self, text=mensaje, font=FUENTE_SUBTITULO, text_color=C_PRIMARY).pack(pady=(25, 10))
        
        self.entry = ctk.CTkEntry(self, font=FUENTE_TEXTO, width=320, height=35)
        self.entry.pack(pady=(0, 20))
        self.entry.focus() # Pone el cursor automáticamente en la caja
        
        # Permitir guardar con la tecla Enter
        self.entry.bind("<Return>", lambda e: self._guardar())

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack()

        ctk.CTkButton(btn_frame, text="💾 Guardar", font=FUENTE_TEXTO, width=110, height=35, fg_color=C_SUCCESS, hover_color="#059669", command=self._guardar).pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="Cancelar", font=FUENTE_TEXTO, width=110, height=35, fg_color=C_CARD, hover_color="#dc2626", command=self._cancelar).pack(side="left", padx=10)

    def _guardar(self):
        self.valor = self.entry.get()
        self.destroy()

    def _cancelar(self):
        self.valor = None
        self.destroy()

    def get_input(self):
        self.master.wait_window(self)
        return self.valor
    
# ===========================================================
# APP PRINCIPAL
# ===========================================================
class NotaApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Generador de Nota de Instalación")
        self.geometry("1050x700")
        self.minsize(800, 600)
        self.configure(fg_color=C_BG)
        self._width_actual = 0
        self.bind("<Configure>", self._responsive_layout)

        self.manager = NotaInstalacionManager(CONFIG_PATH)
        self.componentes_manual = []
        self.rollback_manual = None
        self.bloques_azure = []
        self.bloques_rollback_azure = []
        self._info_azure_actual = None
        self._modo_captura_azure = "principal"
        
        self._drag_idx = -1
        self._drag_lista = None
        self._drag_refresh_callback = None

        self._construir_interfaz()
        self._validar_config_inicial()

    def _limpiar_entry(self, entry):
        entry.delete(0, "end")
        entry.configure(placeholder_text=entry.cget("placeholder_text"))

    def _validar_config_inicial(self):
        if problemas := self.manager.validar_config():
            self._log("⚠ Advertencias:")
            for p in problemas: self._log(f"   - {p}")

    def _construir_interfaz(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
        main.grid_rowconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=0)
        main.grid_columnconfigure(0, weight=1)

        self.tabview = ctk.CTkTabview(main, fg_color=C_PANEL, corner_radius=12, segmented_button_selected_color=C_PRIMARY, segmented_button_selected_hover_color="#0284c7")
        self.tabview.grid(row=0, column=0, sticky="nsew", pady=(0, 15))
        self.tabview.add("Manual (Archivos)")
        self.tabview.add("Azure DevOps")

        self._construir_tab_manual(self.tabview.tab("Manual (Archivos)"))
        self._construir_tab_azure(self.tabview.tab("Azure DevOps"))
        self._construir_salida(main)

    def _responsive_layout(self, event):
        # Solo reaccionar si es la ventana principal la que cambia de tamaño
        if event.widget == self:
            # Evitar cálculos innecesarios si el cambio es de pocos píxeles
            if abs(self._width_actual - event.width) > 20:
                self._width_actual = event.width
                
                # El punto de quiebre: si mide menos de 1050px, es "angosta"
                es_angosto = event.width < 1050

                # --- ADAPTAR PESTAÑA MANUAL ---
                tab_m = self.tabview.tab("Manual (Archivos)")
                if es_angosto:
                    # Apilar verticalmente (Arriba a abajo)
                    self.izq_m.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=10, pady=5)
                    self.der_m.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=10, pady=5)
                    self.bottom_m.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
                    tab_m.grid_rowconfigure(0, weight=1)
                    tab_m.grid_rowconfigure(1, weight=1)
                else:
                    # Lado a lado (Izquierda y Derecha)
                    self.izq_m.grid(row=0, column=0, columnspan=1, sticky="nsew", padx=(0, 10), pady=10)
                    self.der_m.grid(row=0, column=1, columnspan=1, sticky="nsew", padx=(10, 0), pady=10)
                    self.bottom_m.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
                    tab_m.grid_rowconfigure(0, weight=1)
                    tab_m.grid_rowconfigure(1, weight=0)

                # --- ADAPTAR PESTAÑA AZURE ---
                tab_a = self.tabview.tab("Azure DevOps")
                if es_angosto:
                    # Apilar verticalmente
                    self.izq_a.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=10, pady=5)
                    self.der_a.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=10, pady=5)
                    tab_a.grid_rowconfigure(0, weight=1)
                    tab_a.grid_rowconfigure(1, weight=1)
                else:
                    # Lado a lado
                    self.izq_a.grid(row=0, column=0, columnspan=1, sticky="nsew", padx=(0, 10), pady=10)
                    self.der_a.grid(row=0, column=1, columnspan=1, sticky="nsew", padx=(10, 0), pady=10)
                    tab_a.grid_rowconfigure(0, weight=1)
                    tab_a.grid_rowconfigure(1, weight=0)

    def _crear_label_titulo(self, parent, text):
        lbl = ctk.CTkLabel(parent, text=text, font=FUENTE_TITULO, text_color=C_PRIMARY)
        lbl.pack(anchor="w", padx=15, pady=(15, 10))
        return lbl

    # =======================================================
    # TAB MANUAL
    # =======================================================
    def _construir_tab_manual(self, tab):
        tab.grid_rowconfigure(0, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_columnconfigure(1, weight=1)

        izq = ctk.CTkFrame(tab, fg_color=C_BG, corner_radius=12)
        izq.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=10)
        self._crear_label_titulo(izq, "Instalación Principal")
        
        btn_add = ctk.CTkButton(izq, text="➕ Agregar Archivos", font=FUENTE_TEXTO, height=40, fg_color=C_PRIMARY, command=self._agregar_componente_manual)
        btn_add.pack(fill="x", padx=15, pady=5)
        self.lista_componentes_frame = ctk.CTkScrollableFrame(izq, fg_color="transparent")
        self.lista_componentes_frame.pack(fill="both", expand=True, padx=5, pady=5)

        der = ctk.CTkFrame(tab, fg_color=C_BG, corner_radius=12)
        der.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=10)
        self._crear_label_titulo(der, "Rollback (ZIP / Archivos)")
        
        botones_rb = ctk.CTkFrame(der, fg_color="transparent")
        botones_rb.pack(fill="x", padx=15, pady=5)
        ctk.CTkButton(botones_rb, text="📦 Subir ZIP", font=FUENTE_TEXTO, height=35, fg_color=C_PRIMARY, command=self._definir_rollback_manual).pack(side="left", expand=True, fill="x", padx=(0, 5))
        ctk.CTkButton(botones_rb, text="➕ Extra", font=FUENTE_TEXTO, height=35, fg_color=C_CARD, hover_color="#475569", command=self._agregar_componente_extra_rollback).pack(side="left", expand=True, fill="x", padx=5)
        ctk.CTkButton(botones_rb, text="✖ Quitar", font=FUENTE_TEXTO, height=35, fg_color=C_DANGER, hover_color="#dc2626", command=self._quitar_rollback_manual).pack(side="right", expand=True, fill="x", padx=(5, 0))

        self.lbl_rollback = ctk.CTkLabel(der, text="Sin rollback definido.", text_color=C_MUTED, font=FUENTE_TEXTO)
        self.lbl_rollback.pack(anchor="w", padx=15, pady=5)

        # === INTERFAZ FUTURA PARA RUTAS DEL ZIP (COMENTADA) ===
        """
        self.rutas_zip_frame = ctk.CTkFrame(der, fg_color="transparent")
        self.entry_zip_drive = ctk.CTkEntry(self.rutas_zip_frame, placeholder_text="Drive del ZIP", font=FUENTE_CHICA, height=30)
        self.entry_zip_drive.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.entry_zip_azure = ctk.CTkEntry(self.rutas_zip_frame, placeholder_text="Azure del ZIP", font=FUENTE_CHICA, height=30)
        self.entry_zip_azure.pack(side="left", fill="x", expand=True)
        
        self.entry_zip_drive.bind("<KeyRelease>", lambda e: self.rollback_manual.update({"drive": self.entry_zip_drive.get()}) if self.rollback_manual else None)
        self.entry_zip_azure.bind("<KeyRelease>", lambda e: self.rollback_manual.update({"azure": self.entry_zip_azure.get()}) if self.rollback_manual else None)
        
        # Nota: Recuerda agregar self.rutas_zip_frame.pack(...) en _definir_rollback_manual
        # y self.rutas_zip_frame.pack_forget() en _quitar_rollback_manual cuando lo actives.
        """

        self.lista_rollback_frame = ctk.CTkScrollableFrame(der, fg_color="transparent")
        self.lista_rollback_frame.pack(fill="both", expand=True, padx=5, pady=5)

        bottom = ctk.CTkFrame(tab, fg_color=C_BG, corner_radius=12)
        bottom.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        bottom.grid_columnconfigure((0, 1, 2), weight=1)

        f_izq = ctk.CTkFrame(bottom, fg_color="transparent")
        f_izq.grid(row=0, column=0, sticky="nsew", padx=15, pady=15)
        ctk.CTkLabel(f_izq, text="Excepto a:", font=FUENTE_TEXTO).pack(anchor="w", padx=5)
        self.entry_excepto_manual = ctk.CTkEntry(f_izq, placeholder_text="N/A", font=FUENTE_TEXTO, height=35)
        self.entry_excepto_manual.pack(fill="x", padx=5, pady=(2, 5))

        f_cen = ctk.CTkFrame(bottom, fg_color="transparent")
        f_cen.grid(row=0, column=1, sticky="nsew", padx=15, pady=15)
        ctk.CTkLabel(f_cen, text="Equipo de escalamiento:", font=FUENTE_TEXTO).pack(anchor="w", padx=5)
        self.combo_equipo_manual = ctk.CTkComboBox(f_cen, values=["-- Todas las personas --"] + self.manager.listar_nombres_equipos(), font=FUENTE_TEXTO, height=35,state="readonly")
        self.combo_equipo_manual.pack(fill="x", padx=5, pady=(2, 5))
        self.check_incluir_escalamiento_manual = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(f_cen, text="Incluir escalamiento", variable=self.check_incluir_escalamiento_manual, font=FUENTE_TEXTO, fg_color=C_PRIMARY).pack(anchor="w", padx=5, pady=5)

        f_der = ctk.CTkFrame(bottom, fg_color="transparent")
        f_der.grid(row=0, column=2, sticky="nsew", padx=15, pady=15)
        ctk.CTkButton(f_der, text="🧾 Generar Nota Manual", font=FUENTE_SUBTITULO, fg_color=C_SUCCESS, hover_color="#059669", height=50, command=self._generar_nota_manual).pack(side="right", fill="x", expand=True, padx=10)
        # Guardar referencias para el diseño responsivo
        self.izq_m = izq
        self.der_m = der
        self.bottom_m = bottom

    def _crear_tarjeta(self, parent, comp, idx, lista, refresh_cb):
        card = ctk.CTkFrame(parent, fg_color=C_CARD, corner_radius=8, border_width=1, border_color="#475569")
        card.pack(fill="x", padx=5, pady=6, ipadx=5, ipady=8)
        
        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(0, 5))
        
        lbl_drag = ctk.CTkLabel(top, text="☰", font=("Segoe UI", 16, "bold"), text_color=C_MUTED, cursor="hand2")
        lbl_drag.pack(side="left", padx=(0, 12))
        lbl_drag.bind("<ButtonPress-1>", lambda e: self._on_drag_start(e, idx, lista, refresh_cb, card))
        lbl_drag.bind("<ButtonRelease-1>", lambda e: self._on_drag_release(e, parent))

        ctk.CTkLabel(top, text=f"{idx+1}. {comp['nombre']}", font=FUENTE_SUBTITULO, text_color=C_TEXT).pack(side="left")
        ctk.CTkButton(top, text="🗑", width=30, fg_color="transparent", text_color=C_DANGER, hover_color="#475569", command=lambda: (lista.pop(idx), refresh_cb())).pack(side="right")

        ctk.CTkLabel(card, text=f"MD5: {comp['md5']}", font=FUENTE_CHICA, text_color=C_MUTED).pack(anchor="w", padx=42, pady=(0, 8))

        campos = ctk.CTkFrame(card, fg_color="transparent")
        campos.pack(fill="x", padx=40)
        campos.grid_columnconfigure((0, 1, 2), weight=1)
        
        # 1. Caja para IP
        ent_ip = ctk.CTkEntry(campos, placeholder_text="IP (Opcional)", font=FUENTE_CHICA, height=30)
        ent_ip.grid(row=0, column=0, sticky="ew", padx=3)
        if comp.get("ip"): 
            ent_ip.insert(0, comp["ip"])
        ent_ip.bind("<KeyRelease>", lambda e: comp.update({"ip": ent_ip.get()}))

        # 2. Caja para BD
        ent_bd = ctk.CTkEntry(campos, placeholder_text="BD (Opcional)", font=FUENTE_CHICA, height=30)
        ent_bd.grid(row=0, column=1, sticky="ew", padx=3)
        if comp.get("bd"): 
            ent_bd.insert(0, comp["bd"])
        ent_bd.bind("<KeyRelease>", lambda e: comp.update({"bd": ent_bd.get()}))

        # 3. Caja para Drive
        ent_drv = ctk.CTkEntry(campos, placeholder_text="Drive (Opcional)", font=FUENTE_CHICA, height=30)
        ent_drv.grid(row=0, column=2, sticky="ew", padx=3)
        if comp.get("drive"): 
            ent_drv.insert(0, comp["drive"])
        ent_drv.bind("<KeyRelease>", lambda e: comp.update({"drive": ent_drv.get()}))

        # === INTERFAZ FUTURA PARA AZURE Y DRIVE (COMENTADA) ===
        """
        campos.grid_columnconfigure((0, 1), weight=1)
        
        # Fila 0: Cajas IP y BD
        ent_ip = ctk.CTkEntry(campos, placeholder_text="IP (Opcional)", font=FUENTE_CHICA, height=30)
        ent_ip.grid(row=0, column=0, sticky="ew", padx=3, pady=3)
        if comp.get("ip"): ent_ip.insert(0, comp["ip"])
        ent_ip.bind("<KeyRelease>", lambda e: comp.update({"ip": ent_ip.get()}))

        ent_bd = ctk.CTkEntry(campos, placeholder_text="BD (Opcional)", font=FUENTE_CHICA, height=30)
        ent_bd.grid(row=0, column=1, sticky="ew", padx=3, pady=3)
        if comp.get("bd"): ent_bd.insert(0, comp["bd"])
        ent_bd.bind("<KeyRelease>", lambda e: comp.update({"bd": ent_bd.get()}))

        # Fila 1: Cajas Drive y Azure
        ent_drv = ctk.CTkEntry(campos, placeholder_text="Ruta Drive", font=FUENTE_CHICA, height=30)
        ent_drv.grid(row=1, column=0, sticky="ew", padx=3, pady=3)
        if comp.get("drive"): ent_drv.insert(0, comp["drive"])
        ent_drv.bind("<KeyRelease>", lambda e: comp.update({"drive": ent_drv.get()}))
        
        ent_azr = ctk.CTkEntry(campos, placeholder_text="Ruta Azure", font=FUENTE_CHICA, height=30)
        ent_azr.grid(row=1, column=1, sticky="ew", padx=3, pady=3)
        if comp.get("azure"): ent_azr.insert(0, comp["azure"])
        ent_azr.bind("<KeyRelease>", lambda e: comp.update({"azure": ent_azr.get()}))
        """

    def _on_drag_start(self, event, idx, lista, cb, card_widget):
        self._drag_idx, self._drag_lista, self._drag_refresh_callback = idx, lista, cb
        card_widget.configure(border_width=2, border_color=C_PRIMARY) # Feedback visual

    def _on_drag_release(self, event, parent_frame):
        if self._drag_idx < 0 or not self._drag_lista: return
        
        # Calcular posición exacta dentro del contenedor principal
        y_rel = parent_frame.winfo_pointery() - parent_frame.winfo_rooty()
        altura_tarjeta = 110 # Altura aprox de cada tarjeta con padding
        nuevo_idx = max(0, min(len(self._drag_lista) - 1, int(y_rel / altura_tarjeta)))
        
        if nuevo_idx != self._drag_idx:
            item = self._drag_lista.pop(self._drag_idx)
            self._drag_lista.insert(nuevo_idx, item)
            
        self._drag_idx, self._drag_lista = -1, None
        self._drag_refresh_callback()

    def _refrescar_lista_componentes(self):
        for w in self.lista_componentes_frame.winfo_children(): w.destroy()
        for i, c in enumerate(self.componentes_manual): self._crear_tarjeta(self.lista_componentes_frame, c, i, self.componentes_manual, self._refrescar_lista_componentes)

    def _refrescar_lista_rollback(self):
        for w in self.lista_rollback_frame.winfo_children(): w.destroy()
        if not self.rollback_manual: return
        for i, c in enumerate(self.rollback_manual.get("componentes", [])): self._crear_tarjeta(self.lista_rollback_frame, c, i, self.rollback_manual["componentes"], self._refrescar_lista_rollback)

    def _agregar_componente_manual(self):
        for r in filedialog.askopenfilenames(title="Selecciona archivos"):
            try: self.componentes_manual.append({"nombre": os.path.basename(r), "md5": self.manager.calcular_md5(r), "ip": "", "bd": "", "drive": "","azure": ""})
            except Exception as e: messagebox.showerror("Error", f"{r}\n{e}")
        self._refrescar_lista_componentes()

    def _definir_rollback_manual(self):
        if not (r := filedialog.askopenfilename(title="Selecciona ZIP de rollback", filetypes=[("ZIP", "*.zip"), ("Todos", "*.*")])): return
        try: md5_z = self.manager.calcular_md5(r)
        except Exception as e: return messagebox.showerror("Error", str(e))
        items = []
        try:
            for i in self.manager.extraer_componentes_de_zip(r): items.append({**i, "ip": "", "bd": "", "drive": "","azure": ""})
        except Exception: pass
        self.rollback_manual = {"nombre": os.path.basename(r), "md5": md5_z, "drive": "", "componentes": items}
        self.lbl_rollback.configure(text=f"📦 {self.rollback_manual['nombre']} ({len(items)} archivos)", text_color=C_TEXT)
        self._refrescar_lista_rollback()

    def _agregar_componente_extra_rollback(self):
        if not self.rollback_manual: return messagebox.showwarning("Aviso", "Primero define el ZIP de rollback.")
        for r in filedialog.askopenfilenames(title="Selecciona archivo(s) extra"):
            try: self.rollback_manual["componentes"].append({"nombre": os.path.basename(r), "md5": self.manager.calcular_md5(r), "ip": "", "bd": "", "drive": "","azure": ""})
            except Exception as e: messagebox.showerror("Error", f"{r}\n{e}")
        self._refrescar_lista_rollback()

    def _quitar_rollback_manual(self):
        self.rollback_manual = None
        self.lbl_rollback.configure(text="Sin rollback definido.", text_color=C_MUTED)
        self._refrescar_lista_rollback()

    def _generar_nota_manual(self):
        if not self.componentes_manual: return messagebox.showwarning("Aviso", "Agrega al menos un componente principal.")
        self._mostrar_resultado(self.manager.armar_nota_manual(self.componentes_manual, self.entry_excepto_manual.get().strip() or "N/A", self.rollback_manual, self.combo_equipo_manual.get(), self.check_incluir_escalamiento_manual.get()))

    # =======================================================
    # TAB AZURE
    # =======================================================
    def _construir_tab_azure(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_columnconfigure(1, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        izq = ctk.CTkScrollableFrame(tab, fg_color=C_BG, corner_radius=12)
        izq.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=10)
        
        modo_frame = ctk.CTkFrame(izq, fg_color=C_CARD, corner_radius=8)
        modo_frame.pack(fill="x", padx=15, pady=15)
        ctk.CTkLabel(modo_frame, text="Modo de Captura:", font=FUENTE_SUBTITULO).pack(side="left", padx=15, pady=15)
        self.combo_modo_captura = ctk.CTkComboBox(modo_frame, values=["Instalación principal", "Rollback"], font=FUENTE_TEXTO, height=35, command=lambda v: setattr(self, '_modo_captura_azure', "rollback" if v == "Rollback" else "principal"))
        self.combo_modo_captura.pack(side="left", expand=True, fill="x", padx=15, pady=15)

        self._crear_label_titulo(izq, "Conexión y Búsqueda")

        def crear_fila_proj(parent, label, get_func, tipo):
            
            # Función auxiliar para asegurar que siempre devolvemos strings válidos (nunca None)
            def obtener_valores_limpios():
                valores_crudos = get_func()
                if not valores_crudos:
                    return [""]
                # Filtra valores None y los convierte a string
                limpios = [str(v) for v in valores_crudos if v is not None and str(v).strip() != ""]
                return limpios if limpios else [""]

            f = ctk.CTkFrame(parent, fg_color="transparent")
            f.pack(fill="x", padx=15, pady=6)
            ctk.CTkLabel(f, text=label, font=FUENTE_TEXTO).pack(anchor="w")
            
            box = ctk.CTkFrame(f, fg_color="transparent")
            box.pack(fill="x", pady=(4, 0))
            
            # Carga inicial segura
            valores_iniciales = obtener_valores_limpios()
            cb = ctk.CTkComboBox(box, values=valores_iniciales, font=FUENTE_TEXTO, height=35)
            cb.pack(side="left", fill="x", expand=True)
            cb.set(valores_iniciales[0])

            def agregar_nuevo():
                # Mandamos llamar nuestro nuevo diálogo oscuro
                dialogo = DialogoEntradaTexto(self, "Nuevo Proyecto", "Ingresa el nombre del nuevo proyecto:")
                n = dialogo.get_input()
                
                if n and n.strip():
                    self.manager.agregar_proyecto(tipo, n.strip())
                    nuevos = obtener_valores_limpios()
                    cb.configure(values=nuevos)
                    cb.set(n.strip())

            def eliminar_actual():
                val = cb.get()
                if val:
                    self.manager.eliminar_proyecto(tipo, val)
                nuevos = obtener_valores_limpios()
                cb.configure(values=nuevos)
                cb.set(nuevos[0])

            # Botones con funciones claras (sin lambdas anidados que causan bugs)
            boton_agregar = ctk.CTkButton(box, text="➕", width=35, height=35, fg_color=C_CARD, hover_color="#475569", command=agregar_nuevo)
            if tipo == "azure":
                ToolTip(boton_agregar, "Agregar nuevo proyecto a la lista de proyectos configurados.\n(Ej. Compras.RMI)")
            elif tipo == "nota":
                ToolTip(boton_agregar, "Agregar nuevo proyecto a la lista de proyectos de GCP.\n(Ej. cpl-corp...)")
            boton_agregar.pack(side="left", padx=(8, 4))
            ctk.CTkButton(box, text="🗑", width=35, height=35, fg_color=C_DANGER, hover_color="#dc2626", command=eliminar_actual).pack(side="left")
            
            return cb

        self.entry_org_azure = ctk.CTkEntry(izq, placeholder_text="Organización Azure", font=FUENTE_TEXTO, height=35)
        self.entry_org_azure.pack(fill="x", padx=15, pady=6)
        if self.manager.organization: self.entry_org_azure.insert(0, self.manager.organization)
        self.combo_proj_azure = crear_fila_proj(izq, "Proyecto API DevOps:", self.manager.listar_proyectos_configurados, "azure")
        self.combo_proj_nota = crear_fila_proj(izq, "Proyecto Texto (Ej. cpl-corp...):", self.manager.listar_proyectos_nota_configurados, "nota")

        busqueda = ctk.CTkFrame(izq, fg_color="transparent")
        busqueda.pack(fill="x", padx=15, pady=12)
        ctk.CTkButton(busqueda, text="🔎 Buscar Componente", font=FUENTE_TEXTO, height=35, fg_color=C_PRIMARY, command=self._abrir_buscador_por_componente).pack(side="left", expand=True, fill="x", padx=(0, 6))
        self.entry_release_id = ctk.CTkEntry(busqueda, placeholder_text="O ID directo", font=FUENTE_TEXTO, height=35, width=100)
        self.entry_release_id.pack(side="left", fill="x", padx=(6, 6))
        ctk.CTkButton(busqueda, text="⬇ Traer", font=FUENTE_TEXTO, height=35, width=70, fg_color=C_SUCCESS, command=self._traer_datos_azure).pack(side="left")

        ctk.CTkButton(izq, text="🔎 Buscar tag en logs de azure (lento)", font=FUENTE_TEXTO, height=35, fg_color=C_CARD, hover_color="#475569", command=self._buscar_tag_en_logs).pack(fill="x", padx=15, pady=(5, 10))
        self.lbl_info_azure = ctk.CTkLabel(izq, text="Esperando conexión...", text_color=C_MUTED, font=FUENTE_TEXTO)
        self.lbl_info_azure.pack(anchor="w", padx=15, pady=5)

        self._crear_label_titulo(izq, "Datos Principales")
        for attr, ph in [("entry_componente_azure", "Componente"), ("entry_rama_azure", "Rama"), ("entry_commit_azure", "Commit Release"), ("entry_pr_number_azure", "PR a Master (Número)")]:
            e = ctk.CTkEntry(izq, placeholder_text=ph, font=FUENTE_TEXTO, height=32)
            e.pack(fill="x", padx=15, pady=4)
            setattr(self, attr, e)

        self._crear_label_titulo(izq, "Datos Adicionales")
        for attr, ph in [("entry_tag", "Tag version (ej. 1.4.2)"), ("entry_commit_prop", "Commit properties"), ("entry_url_prop", "URL properties"), ("entry_commit_env", "Commit environment.ts"), ("entry_url_env", "Url environment.ts")]:
            e = ctk.CTkEntry(izq, placeholder_text=ph, font=FUENTE_TEXTO, height=32)
            e.pack(fill="x", padx=15, pady=4)
            setattr(self, attr, e)

        ctk.CTkLabel(izq, text="Variables (clave : valor):", font=FUENTE_TEXTO).pack(anchor="w", padx=15, pady=(12, 0))
        self.text_variables = ctk.CTkTextbox(izq, height=75, font=FUENTE_TEXTO, fg_color=C_CARD)
        self.text_variables.pack(fill="x", padx=15, pady=(4, 15))
        
        boton_agregar_nota = ctk.CTkButton(izq, text="➕ Agregar Bloque a la Nota", font=FUENTE_SUBTITULO, height=45, fg_color=C_SUCCESS, hover_color="#059669", command=self._agregar_bloque_azure)
        ToolTip(boton_agregar_nota, "Agrega el bloque a la nota final. Puedes agregar varios bloques antes de generar la nota completa. (Componentes o Rollback)")
        boton_agregar_nota.pack(fill="x", padx=15, pady=(10, 20))

        # Derecha Azure
        der = ctk.CTkScrollableFrame(tab, fg_color=C_BG, corner_radius=12)
        der.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=10)

        self._crear_label_titulo(der, "Bloques (Principal)")
        self.lista_bloques_frame = ctk.CTkFrame(der, fg_color="transparent")
        self.lista_bloques_frame.pack(fill="x", padx=15, pady=5)

        self._crear_label_titulo(der, "Bloques (Rollback)")
        self.lista_bloques_rollback_frame = ctk.CTkFrame(der, fg_color="transparent")
        self.lista_bloques_rollback_frame.pack(fill="x", padx=15, pady=5)

        self._crear_label_titulo(der, "Configuración Adicional")
        ctk.CTkLabel(der, text="Excepto a:", font=FUENTE_TEXTO).pack(anchor="w", padx=15, pady=(5, 0))
        self.entry_excepto_azure = ctk.CTkEntry(der, placeholder_text="N/A", font=FUENTE_TEXTO, height=35)
        self.entry_excepto_azure.pack(fill="x", padx=15, pady=(2, 15))

        self.check_incluir_backup = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(der, text="Incluir bloque de Backup SRE", variable=self.check_incluir_backup, command=lambda: (self.entry_backup_componente.configure(state="normal" if self.check_incluir_backup.get() else "disabled"), self.text_backup_pasos.configure(state="normal" if self.check_incluir_backup.get() else "disabled")), font=FUENTE_TEXTO, fg_color=C_PRIMARY).pack(anchor="w", padx=15, pady=5)
        self.entry_backup_componente = ctk.CTkEntry(der, placeholder_text="Componente del backup", state="disabled", font=FUENTE_TEXTO, height=35)
        self.entry_backup_componente.pack(fill="x", padx=15, pady=4)
        self.text_backup_pasos = ctk.CTkTextbox(der, height=80, state="disabled", font=FUENTE_TEXTO, fg_color=C_CARD)
        self.text_backup_pasos.pack(fill="x", padx=15, pady=(2, 15))

        ctk.CTkLabel(der, text="Equipo para escalamiento:", font=FUENTE_TEXTO).pack(anchor="w", padx=15, pady=(10, 0))
        self.combo_equipo_azure = ctk.CTkComboBox(der, values=["-- Todas las personas --"] + self.manager.listar_nombres_equipos(), font=FUENTE_TEXTO, height=35,state="readonly")
        self.combo_equipo_azure.pack(fill="x", padx=15, pady=(2, 20))

        ctk.CTkButton(der, text="🧾 Generar Nota Completa", font=FUENTE_SUBTITULO, height=50, fg_color=C_SUCCESS, hover_color="#059669", command=self._generar_nota_azure).pack(fill="x", padx=15, pady=10)
        # Guardar referencias para el diseño responsivo
        self.izq_a = izq
        self.der_a = der

    
    def _abrir_buscador_por_componente(self):
        org, pro = self.entry_org_azure.get().strip(), self.combo_proj_azure.get().strip()
        if not org or not pro: return messagebox.showwarning("Aviso", "Completa Organización y Proyecto.")
        if not self.manager.pat: return messagebox.showerror("Error", "Falta PAT en config.json")
        
        def al_seleccionar(r):
            self._limpiar_entry(self.entry_release_id)
            self.entry_release_id.insert(0, str(r['id']))
            self.lbl_info_azure.configure(text="Descargando datos del release... ⏳", text_color="#f1c40f")
            
            # Trabajo en hilo secundario
            def tarea_fondo():
                try:
                    release_completo = self.manager.obtener_release(pro, r['id'])
                    self.after(0, lambda: self._cargar_info_desde_release(release_completo, pro))
                except Exception as e:
                    self.after(0, lambda e=e: messagebox.showerror("Error", f"No se pudo descargar el release completo: {e}"))
            
            threading.Thread(target=tarea_fondo, daemon=True).start()

        PipelineReleaseSearchDialog(self, self.manager, org, pro, al_seleccionar)

    def _cargar_info_desde_release(self, release, proyecto):
        try:
            info = self.manager._armar_info_desde_release(release, proyecto)
            self._info_azure_actual = info
            for a, k in [("entry_componente_azure", "componente"), ("entry_rama_azure", "rama"), ("entry_commit_azure", "commit_release"), ("entry_pr_number_azure", "pr_number")]:
                self._limpiar_entry(getattr(self, a))
                getattr(self, a).insert(0, str(info.get(k) or ""))
            self._limpiar_entry(self.entry_tag)
            if info.get("tag_version_sugerido"): self.entry_tag.insert(0, info["tag_version_sugerido"])
            para_ui_extra = [
                ("entry_commit_prop", "commit_properties"),
                ("entry_url_prop", "url_properties"),
                ("entry_commit_env", "commit_environment"),
                ("entry_url_env", "url_environment")
            ]
            for atributo, clave_info in para_ui_extra:
                caja_texto = getattr(self, atributo)
                self._limpiar_entry(caja_texto)
                valor = info.get(clave_info)
                if valor:
                    caja_texto.insert(0, str(valor))
            self.lbl_info_azure.configure(text=f"Build: {info['version_build']} | Release: {info['release']}", text_color=C_SUCCESS)
            for w in info.get("_warnings", []): self._log(f"   ⚠ {w}")
        except Exception as e: messagebox.showerror("Error", str(e))

    def _traer_datos_azure(self):
        org, pro, rid = self.entry_org_azure.get().strip(), self.combo_proj_azure.get().strip(), self.entry_release_id.get().strip()
        if not org or not pro or not rid: return messagebox.showwarning("Aviso", "Completa Org, Proyecto y Release ID.")
        self.manager.organization = org
        
        # 1. Avisar al usuario en la UI que estamos trabajando
        self.lbl_info_azure.configure(text="Descargando datos de Azure... ⏳", text_color="#f1c40f")
        
        # 2. Definir el trabajo pesado
        def tarea_fondo():
            try:
                # Esto es lo que congela la app, ahora lo hace el hilo secundario
                release = self.manager.obtener_release(pro, rid)
                
                # 3. Al terminar, manda actualizar la UI al hilo principal
                self.after(0, lambda: self._cargar_info_desde_release(release, pro))
            except Exception as e:
                self.after(0, lambda e=e: messagebox.showerror("Error", str(e)))
                self.after(0, lambda: self.lbl_info_azure.configure(text="Error de conexión.", text_color=C_DANGER))
                
        # 4. Iniciar el hilo
        threading.Thread(target=tarea_fondo, daemon=True).start()

    def _buscar_tag_en_logs(self):
        if not self._info_azure_actual or not self._info_azure_actual.get("_build_id_para_tag"): 
            return messagebox.showwarning("Aviso", "Falta información del build (trae datos primero).")
        
        comp = self.entry_componente_azure.get().strip()
        self._log(f"🔎 Buscando tag para '{comp}' en logs (esto puede tardar unos segundos)...")
        
        def tarea_fondo():
            try:
                # Trabajo pesado en el fondo
                tag, step = self.manager.buscar_tag_en_logs_de_push(self._info_azure_actual["proyecto"], self._info_azure_actual["_build_id_para_tag"], componente=comp)
                
                # Función segura para actualizar la UI
                def actualizar_ui():
                    if tag: 
                        self._limpiar_entry(self.entry_tag)
                        self.entry_tag.insert(0, tag)
                        self._log(f"✅ Tag en '{step}': {tag}")
                    else: 
                        self._log("❌ No se encontró tag en logs automáticamente.")
                        
                self.after(0, actualizar_ui)
            except Exception as e: 
                self.after(0, lambda e=e: messagebox.showerror("Error", str(e)))

        threading.Thread(target=tarea_fondo, daemon=True).start()

    def _refrescar_lista_bloques(self, lista, parent, tipo):
        for w in parent.winfo_children(): w.destroy()
        if not lista: return ctk.CTkLabel(parent, text="Sin bloques.", text_color=C_MUTED, font=FUENTE_CHICA).pack(anchor="w")
        for i, b in enumerate(lista):
            f = ctk.CTkFrame(parent, fg_color=C_CARD, corner_radius=6, border_width=1, border_color="#475569")
            f.pack(fill="x", pady=4)
            p = next((l for l in b.splitlines() if l.strip()), f"Bloque {i+1}")
            ctk.CTkLabel(f, text=f"{i+1}. {p[:40]}...", font=FUENTE_CHICA, text_color=C_TEXT).pack(side="left", padx=12, pady=10)
            ctk.CTkButton(f, text="🗑", width=30, fg_color="transparent", text_color=C_DANGER, hover_color="#475569", command=lambda idx=i: (lista.pop(idx), self._refrescar_lista_bloques(lista, parent, tipo))).pack(side="right", padx=10)

    def _agregar_bloque_azure(self):
        if not self._info_azure_actual: return messagebox.showwarning("Aviso", "Trae datos de Azure primero.")
        v_dict = {k.strip(): v.strip() for k, v in [l.split(":", 1) for l in self.text_variables.get("1.0", "end").splitlines() if ":" in l] if k.strip()}
        c_f, r_f, com_f, pr_f = self.entry_componente_azure.get().strip(), self.entry_rama_azure.get().strip(), self.entry_commit_azure.get().strip(), self.entry_pr_number_azure.get().strip()
        p_az, p_no = self._info_azure_actual["proyecto"], self.combo_proj_nota.get().strip()
        inf = dict(self._info_azure_actual)
        inf.update({"proyecto": p_no or p_az, "componente": c_f, "rama": r_f, "commit_release": com_f, "url_repositorio": f"https://dev.azure.com/{self.manager.organization}/{p_az}/_git/{c_f}" if c_f else "", "pr_a_master": f"https://dev.azure.com/{self.manager.organization}/{p_az}/_git/{c_f}/pullrequest/{pr_f}" if c_f and pr_f else ""})
        
        bloque = self.manager.bloque_azure_componente(inf, variables=v_dict, tag_version=self.entry_tag.get().strip(), commit_properties=self.entry_commit_prop.get().strip(), url_properties=self.entry_url_prop.get().strip(), commit_environment=self.entry_commit_env.get().strip(), url_environment=self.entry_url_env.get().strip())
        
        lista, frame, t = (self.bloques_rollback_azure, self.lista_bloques_rollback_frame, "rollback") if self._modo_captura_azure == "rollback" else (self.bloques_azure, self.lista_bloques_frame, "principal")
        lista.append(bloque)
        self._refrescar_lista_bloques(lista, frame, t)

        self._info_azure_actual = None
        self.lbl_info_azure.configure(text="Esperando conexión...", text_color=C_MUTED)
        for e in [self.entry_release_id, self.entry_componente_azure, self.entry_rama_azure, self.entry_commit_azure, self.entry_pr_number_azure, self.entry_tag, self.entry_commit_prop, self.entry_url_prop, self.entry_commit_env, self.entry_url_env]: self._limpiar_entry(e)
        self.text_variables.delete("1.0", "end")

    def _generar_nota_azure(self):
        if not self.bloques_azure: return messagebox.showwarning("Aviso", "Agrega al menos un bloque principal.")
        bt = self.manager.bloque_backup_sre(self.entry_backup_componente.get().strip() or "Componente", [l.strip() for l in self.text_backup_pasos.get("1.0", "end").splitlines() if l.strip()]) if self.check_incluir_backup.get() else ""
        self._mostrar_resultado(self.manager.armar_nota_azure(self.bloques_azure, self.entry_excepto_azure.get().strip() or "N/A", self.bloques_rollback_azure or None, bt, self.combo_equipo_azure.get()))

    def _validar_config_inicial(self):
        # --- NUEVO: Pedir PAT con el diálogo de diseño personalizado ---
        if not self.manager.pat:
            # Llamamos a nuestra nueva clase en lugar del genérico CTkInputDialog
            dialog = DialogoTokenAzure(self)
            nuevo_pat = dialog.get_input()
            
            if nuevo_pat and nuevo_pat.strip():
                if "azure" not in self.manager._data_cache:
                    self.manager._data_cache["azure"] = {}
                
                self.manager._data_cache["azure"]["pat"] = nuevo_pat.strip()
                self.manager.guardar_config()
                self.manager._cargar_config()
                self._log("✅ Token de Azure configurado y guardado exitosamente.")
            else:
                self._log("⚠ Advertencia: Iniciaste sin Token de Azure. Las descargas fallarán.")

        # --- Validaciones normales ---
        if problemas := self.manager.validar_config():
            self._log("⚠ Advertencias de configuración:")
            for p in problemas: 
                self._log(f"   - {p}")
    # =======================================================
    # TERMINAL / OUTPUT
    # =======================================================
    def _construir_salida(self, main):
        frame = ctk.CTkFrame(main, fg_color=C_BG, corner_radius=12)
        frame.grid(row=1, column=0, sticky="nsew")
        frame.grid_rowconfigure(1, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        h = ctk.CTkFrame(frame, fg_color="transparent")
        h.grid(row=0, column=0, sticky="ew", padx=15, pady=(10, 5))
        ctk.CTkLabel(h, text="Resultado", font=FUENTE_SUBTITULO, text_color=C_PRIMARY).pack(side="left")
        ctk.CTkButton(h, text="Limpiar", font=FUENTE_TEXTO, width=80, fg_color=C_CARD, hover_color="#475569", command=lambda: self.terminal.delete("1.0", "end")).pack(side="right", padx=5)
        ctk.CTkButton(h, text="💾 Guardar", font=FUENTE_TEXTO, width=90, fg_color=C_PRIMARY, command=self._guardar_resultado).pack(side="right", padx=5)
        ctk.CTkButton(h, text="📋 Copiar", font=FUENTE_TEXTO, width=90, fg_color=C_SUCCESS, hover_color="#059669", command=self._copiar_resultado).pack(side="right", padx=5)

        self.terminal = ctk.CTkTextbox(frame, fg_color=C_PANEL, text_color=C_TEXT, font=("Consolas", 13), border_width=1, border_color=C_CARD, height=150)
        self.terminal.grid(row=1, column=0, sticky="nsew", padx=15, pady=(0, 15))

    def _mostrar_resultado(self, texto):
        self.terminal.delete("1.0", "end")
        self.terminal.insert("end", texto + "\n\n✅ Nota generada.")
        self.clipboard_clear()
        self.clipboard_append(texto)

    def _copiar_resultado(self):
        self.clipboard_clear()
        self.clipboard_append(self.terminal.get("1.0", "end").strip())

    def _guardar_resultado(self):
        if (c := self.terminal.get("1.0", "end").strip()) and (r := filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Texto", "*.txt")])):
            with open(r, "w", encoding="utf-8") as f: f.write(c)

    def _log(self, text):
        self.terminal.insert("end", text + "\n")
        self.terminal.see("end")
    

if __name__ == "__main__":
    app = NotaApp()
    app.mainloop()