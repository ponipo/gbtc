# app_with_auth.py – 面談練習システム (認証機能付き)
# ===================================================
# ❶ すべての import の直後に set_page_config を呼び出す
import os, io, zipfile, datetime

import streamlit as st
from openai import OpenAI
from dotenv import load_dotenv
from supabase import create_client, Client
from audio_recorder_streamlit import audio_recorder

st.set_page_config(page_title="GBトレセン")

# ---------- .env 読み込み & クライアント初期化 ----------
load_dotenv()

# --- OpenAI ---
client = OpenAI(api_key=os.getenv("OPENAI_APIKEY"))

# --- Supabase (認証用) ---
AUTH_SUPABASE_URL = os.getenv("AUTH_SUPABASE_URL")
AUTH_SUPABASE_KEY = os.getenv("AUTH_SUPABASE_KEY")
auth_supabase: Client = create_client(AUTH_SUPABASE_URL, AUTH_SUPABASE_KEY)


# ---------- 認証関数 (GBUniv.py より) ----------
def authenticate_user(email: str, password: str):
    """
    users テーブルで:
      ・mail == email
      ・pass == password
      ・auth == 0（承認済み）
    を満たすレコードがあるか確認。
    """
    try:
        res = (
            auth_supabase.table("users")
            .select("*")
            .eq("mail", email)
            .eq("pass", password)
            .execute()
        )
        data = res.data
        if data:
            user = data[0]
            if int(user.get("auth", 1)) == 0:
                return True, user, "ログイン成功しました。"
        return False, None, "メールまたはパスワードが正しくありません。"
    except Exception as e:
        st.error(f"データベース接続エラー: {e}") # ユーザーに見せるエラーを少し具体的に
        return False, None, f"認証エラー: {e}"

# ---------- rerun の互換ヘルパ (GBUniv.py より) ----------
def do_rerun():
    if hasattr(st, "rerun"):
        st.rerun()                 # Streamlit 1.30 以降
    else:
        st.experimental_rerun()    # 旧バージョン用

# ---------- セッション初期化 ----------
# --- 認証状態 ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user" not in st.session_state:
    st.session_state.user = None
# --- 面談アプリの状態 ---
if "audio_files" not in st.session_state:
    st.session_state.audio_files = []
if "system_prompt" not in st.session_state:
    st.session_state.system_prompt = ""

# ---------- ログイン画面 ----------
def login_view():
    st.title("GBトレセン ログイン")
    email = st.text_input("メールアドレス")
    password = st.text_input("パスワード", type="password")
    if st.button("ログイン"):
        if not email or not password:
            st.error("メールとパスワードを入力してください。")
        else:
            ok, user, msg = authenticate_user(email, password)
            if ok:
                st.session_state.authenticated = True
                st.session_state.user = user
                do_rerun()
            else:
                st.error(msg)

# ---------- 面談練習システム本体 ----------
# (元の app2.py のロジックを関数化)
def main_app_view():
    # --- サイドバー：ユーザー表示 & ログアウト ---
    st.sidebar.write(f"👤 {st.session_state.user.get('mail')}")
    if st.sidebar.button("ログアウト"):
        # セッション情報をクリア
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        do_rerun()

    # --- ここから下は元の app2.py と同じコード ---
    MODEL_NAMES = ["gpt-4o", "gpt-3.5-turbo-1106", "gpt-4-1106-preview"]
    VOICES      = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]

    st.title("GBトレセン")
    selected_model_name = st.selectbox("モデルを選択してください", MODEL_NAMES)
    selected_voice      = st.selectbox("音声を選択してください", VOICES)

    class ChatBot:
        def __init__(self, client, model_name, system_message, max_input_history=2):
            self.client         = client
            self.model_name     = model_name
            self.system_message = {"role": "system", "content": system_message}
            self.input_message_list = [self.system_message]
            self.max_input_history  = max_input_history
        def add_user_message(self, message: str) -> None:
            self.input_message_list.append({"role": "user", "content": message})
        def get_ai_response(self, user_message: str) -> str:
            self.add_user_message(user_message)
            hist = self.input_message_list[1:]
            input_history = [self.system_message] + hist[-2 * self.max_input_history + 1 :]
            response = self.client.chat.completions.create(
                model=self.model_name, messages=input_history, temperature=0,
            )
            ai_response = response.choices[0].message.content
            self.input_message_list.append({"role": "assistant", "content": ai_response})
            return ai_response
        def get_text_log(self) -> str:
            return "\n".join(f"{m['role']}: {m['content']}" for m in self.input_message_list)

    def initialize_chatbot(client, system_prompt):
        if "chatbot" not in st.session_state or st.session_state.system_prompt != system_prompt:
            st.session_state.chatbot = ChatBot(
                client, model_name=selected_model_name, system_message=system_prompt, max_input_history=5
            )
            st.session_state.system_prompt = system_prompt
        return st.session_state.chatbot

    with st.expander("📋 議事録入力 → プロンプト生成", expanded=True):
        minutes_text = st.text_area("議事録入力", placeholder="ここに議事録を貼り付けてください", height=200)
        gen_btn = st.button("システムプロンプトを生成", disabled=not minutes_text.strip())
        if gen_btn:
            st.info("システムプロンプトを生成中 …")
            meta_prompt = (
                "あなたはプロのロールプレイングシナリオライター兼プロンプトエンジニアです。\n"
                "以下の議事録を徹底的に分析し、ユーザーが営業面談の練習をするための、リアルなAIチャットボット用のシステムプロンプト（日本語）を作成してください。\n"
                "AIは『営業を受ける側』の特定の人物として振る舞う必要があります。\n\n"
                "## 指示:\n"
                "1. **登場人物の特定**: 議事録から、ユーザーが営業をかけている相手（キーパーソン）を特定してください。\n"
                "2. **詳細な情報抽出**: 特定した人物と、その人が所属する会社について、以下の情報を議事録から可能な限り詳細に抽出・推測してください。\n"
                "    - **会社情報**: 会社名、事業内容、業界での立ち位置、抱えている課題やニーズ。\n"
                "    - **人物情報（ペルソナ）**: 氏名、部署、役職。\n"
                "    - **キャラクター**: 性格（例: 慎重、決断力がある、懐疑的、協力的など）、話し方の口調や特徴。\n"
                "    - **思考・価値観**: 何を重視しているか（コスト、品質、実績、将来性など）、懸念事項、期待していること。\n"
                "    - **面談の文脈**: これまでの経緯、前回の面談で何が話されたか、今回の面談の目的。\n"
                "3. **システムプロンプトの構築**: 抽出した情報を用いて、以下の構成でシステムプロンプトを作成してください。AIが忠実に役割を演じられるように、具体的かつ詳細な指示を記述することが重要です。\n\n"
                "## 出力テンプレート:\n"
                "あなたは、以下の設定になりきって、ユーザーとのロールプレイングを行ってください。ユーザーはあなたに営業をかける練習をします。あなたの役割を完璧に演じきることが目的です。\n\n"
                "### あなたの役割（ペルソナ）\n"
                "- **会社名**: [会社名]\n"
                "- **所属**: [部署・役職]\n"
                "- **氏名**: [氏名]\n"
                "- **性格・キャラクター**: [議事録から分析した性格や特徴を記述。例: 物事を多角的に検討する慎重な性格。結論を急がず、データや根拠を重視する。]\n"
                "- **話し方**: [議事録から分析した話し方を記述。例: 丁寧語を基本とするが、重要な点では鋭い質問を投げかける。専門用語も交えて話す。]\n"
                "- **考え方・価値観**: [議事録から分析した価値観を記述。例: 短期的なコスト削減よりも、長期的な事業成長に繋がる投資を重視している。導入実績やサポート体制に強い関心がある。]\n\n"
                "### 面談の背景とあなたの状況\n"
                "- **会社の課題**: [会社が直面している課題やニーズを具体的に記述。]\n"
                "- **これまでの経緯**: [ユーザーとのこれまでのやり取りや、前回の面談の要点をまとめる。]\n"
                "- **現在の心境**: [提案に対する期待と懸念を具体的に記述。例: 提案されているソリューションには魅力を感じているが、既存システムとの連携や導入後の運用負荷について懸念している。]\n\n"
                "### ロールプレイングのルール\n"
                "- 上記のペルソナと背景を絶対に守り、一貫した応答をしてください。\n"
                "- ユーザーは前回の面談のやり直し、または続きとして話しかけてきます。自然に応対してください。\n"
                "- あなたがAIや言語モデルであることは絶対に明かしてはいけません。\n"
                "- 受け身にならず、あなたからも積極的に質問や懸念点を投げかけてください。\n"
                "- 簡単には納得せず、ユーザーの提案を様々な角度から吟味し、意思決定者としてリアルな反応を返してください。\n\n"
                "## 最終出力形式:\n"
                "上記テンプレートに沿って生成したシステムプロンプトの本文のみを出力してください。この指示文や分析過程は一切含めないでください。\n"
                "--- 議事録 ---"
            )
            combined_prompt = f"{meta_prompt}\n{minutes_text}"
            sys_prompt_resp = client.chat.completions.create(
                model="gpt-4o", temperature=0.7, messages=[{"role": "user", "content": combined_prompt}],
            )
            generated_prompt = sys_prompt_resp.choices[0].message.content.strip()
            st.session_state.system_prompt = generated_prompt
            st.success("システムプロンプトを更新しました ✅")

    system_prompt_input = st.text_input(
        "システムプロンプトを設定してください", value=st.session_state.system_prompt, key="system_prompt_input",
    )
    st.session_state.system_prompt = system_prompt_input

    if st.session_state.system_prompt.strip():
        chatbot     = initialize_chatbot(client, st.session_state.system_prompt)
        audio_bytes = audio_recorder(key="audio_recorder_main")
        if audio_bytes:
            st.audio(audio_bytes, format="audio/wav")
            st.session_state.audio_files.append(("user", audio_bytes))
            user_audio_file = io.BytesIO(audio_bytes)
            user_audio_file.name = "record.wav"
            transcript = client.audio.transcriptions.create(model="whisper-1", file=user_audio_file)
            st.text(transcript.text)
            response_chatgpt = chatbot.get_ai_response(transcript.text)
            tts_response = client.audio.speech.create(model="tts-1", voice=selected_voice, input=response_chatgpt)
            bot_audio_bytes = tts_response.content
            st.session_state.audio_files.append(("assistant", bot_audio_bytes))
            st.audio(bot_audio_bytes, format="audio/mp3", autoplay=True) # 自動再生を追加すると便利です

    col1, col2 = st.columns(2)
    with col1:
        if "chatbot" in st.session_state:
            text_bytes = st.session_state.chatbot.get_text_log().encode("utf-8")
            st.download_button(
                "💬 会話ログ (TXT) をダウンロード", data=text_bytes, file_name="chat_log.txt", mime="text/plain",
            )
        else:
            st.download_button(
                "💬 会話ログ (TXT) をダウンロード", data=b"", disabled=True, help="まず会話を始めてください", file_name="chat_log.txt", mime="text/plain",
            )
    with col2:
        if st.session_state.audio_files:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for i, (role, bts) in enumerate(st.session_state.audio_files, 1):
                    ext = "wav" if role == "user" else "mp3"
                    zf.writestr(f"{i:03d}_{role}.{ext}", bts)
            buf.seek(0)
            st.download_button(
                "🔊 会話ログ (Audio ZIP) をダウンロード", data=buf, file_name="chat_audio.zip", mime="application/zip",
            )
        else:
            st.download_button(
                "🔊 会話ログ (Audio ZIP) をダウンロード", data=b"", disabled=True, help="まず音声を送ってください", file_name="chat_audio.zip", mime="application/zip",
            )

# ---------- ルーティング (認証状態に応じて表示を切り替え) ----------
if st.session_state.authenticated:
    main_app_view()
else:
    login_view()