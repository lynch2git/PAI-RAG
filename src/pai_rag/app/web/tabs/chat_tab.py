from typing import Dict, Any, List
import gradio as gr
from pai_rag.app.web.rag_client import RagApiError, rag_client
from pai_rag.app.web.ui_constants import (
    SIMPLE_PROMPTS,
    GENERAL_PROMPTS,
    EXTRACT_URL_PROMPTS,
    ACCURATE_CONTENT_PROMPTS,
)


def clear_history(chatbot):
    rag_client.clear_history()
    chatbot = []
    return chatbot, 0


def reset_textbox():
    return gr.update(value="")


def respond(input_elements: List[Any]):
    update_dict = {}

    for element, value in input_elements.items():
        update_dict[element.elem_id] = value

    if update_dict["retrieval_mode"] == "data_analysis":
        update_dict["retrieval_mode"] = "hybrid"
    update_dict["synthesizer_type"] = "SimpleSummarize"

    # empty input.
    if not update_dict["question"]:
        yield update_dict["chatbot"]
        return

    try:
        rag_client.patch_config(update_dict)
    except RagApiError as api_error:
        raise gr.Error(f"HTTP {api_error.code} Error: {api_error.msg}")

    query_type = update_dict["query_type"]
    msg = update_dict["question"]
    chatbot = update_dict["chatbot"]
    is_streaming = update_dict["is_streaming"]

    if chatbot is not None:
        chatbot.append((msg, ""))

    try:
        if query_type == "LLM":
            response_gen = rag_client.query_llm(
                msg, with_history=update_dict["include_history"], stream=is_streaming
            )
        elif query_type == "Retrieval":
            response_gen = rag_client.query_vector(msg)

        elif query_type == "WebSearch":
            response_gen = rag_client.query_search(
                msg, with_history=update_dict["include_history"], stream=is_streaming
            )
        else:
            response_gen = rag_client.query(
                msg, with_history=update_dict["include_history"], stream=is_streaming
            )

        for resp in response_gen:
            chatbot[-1] = (msg, resp.result)
            yield chatbot

    except RagApiError as api_error:
        raise gr.Error(f"HTTP {api_error.code} Error: {api_error.msg}")
    except Exception as e:
        raise gr.Error(f"Error: {e}")
    finally:
        yield chatbot


def create_chat_tab() -> Dict[str, Any]:
    with gr.Row():
        with gr.Column(scale=2):
            query_type = gr.Radio(
                ["Retrieval", "LLM", "WebSearch", "RAG (Retrieval + LLM)"],
                label="\N{fire} Which query do you want to use?",
                elem_id="query_type",
                value="RAG (Retrieval + LLM)",
            )
            is_streaming = gr.Checkbox(
                label="Streaming Output",
                info="Streaming Output",
                elem_id="is_streaming",
                value=True,
            )
            with gr.Column(visible=True) as vs_col:
                vec_model_argument = gr.Accordion(
                    "Parameters of Vector Retrieval", open=False
                )
                with vec_model_argument:
                    retrieval_mode = gr.Radio(
                        ["Embedding Only", "Keyword Only", "Hybrid"],
                        label="Retrieval Mode",
                        elem_id="retrieval_mode",
                    )

                    reranker_type = gr.Radio(
                        ["simple-weighted-reranker", "model-based-reranker"],
                        label="Reranker Type",
                        elem_id="reranker_type",
                    )

                    with gr.Column(
                        visible=(reranker_type == "simple-weighted-reranker")
                    ) as simple_reranker_col:
                        vector_weight = gr.Slider(
                            minimum=0,
                            maximum=1,
                            value=0.7,
                            elem_id="vector_weight",
                            label="Weight of embedding retrieval results",
                        )
                        keyword_weight = gr.Slider(
                            minimum=0,
                            maximum=1,
                            value=float(1 - vector_weight.value),
                            elem_id="keyword_weight",
                            label="Weight of keyword retrieval results",
                            interactive=False,
                        )

                    with gr.Column(
                        visible=(reranker_type == "model-based-reranker")
                    ) as model_reranker_col:
                        reranker_model = gr.Radio(
                            [
                                "bge-reranker-base",
                                "bge-reranker-large",
                            ],
                            label="Re-Ranker Model (Note: It will take a long time to load the model when using it for the first time.)",
                            elem_id="reranker_model",
                        )

                    with gr.Column():
                        similarity_top_k = gr.Slider(
                            minimum=0,
                            maximum=100,
                            step=1,
                            elem_id="similarity_top_k",
                            label="Text Top K (choose between 0 and 100)",
                        )
                        image_similarity_top_k = gr.Slider(
                            minimum=0,
                            maximum=10,
                            step=1,
                            elem_id="image_similarity_top_k",
                            label="Image Top K (choose between 0 and 10)",
                        )
                        need_image = gr.Checkbox(
                            label="Inference with multi-modal LLM",
                            info="Inference with multi-modal LLM.",
                            elem_id="need_image",
                        )
                        similarity_threshold = gr.Slider(
                            minimum=0,
                            maximum=1,
                            step=0.01,
                            elem_id="similarity_threshold",
                            label="Similarity Score Threshold (The more similar the items, the bigger the value.)",
                        )

                    def change_weight(change_weight):
                        return round(float(1 - change_weight), 2)

                    vector_weight.input(
                        fn=change_weight,
                        inputs=vector_weight,
                        outputs=[keyword_weight],
                    )

                    def change_reranker_type(reranker_type):
                        if reranker_type == "simple-weighted-reranker":
                            return {
                                simple_reranker_col: gr.update(visible=True),
                                model_reranker_col: gr.update(visible=False),
                            }
                        elif reranker_type == "model-based-reranker":
                            return {
                                simple_reranker_col: gr.update(visible=False),
                                model_reranker_col: gr.update(visible=True),
                            }
                        else:
                            return {
                                simple_reranker_col: gr.update(visible=False),
                                model_reranker_col: gr.update(visible=False),
                            }

                    def change_retrieval_mode(retrieval_mode):
                        if retrieval_mode == "Hybrid":
                            return {simple_reranker_col: gr.update(visible=True)}
                        else:
                            return {simple_reranker_col: gr.update(visible=False)}

                    reranker_type.input(
                        fn=change_reranker_type,
                        inputs=reranker_type,
                        outputs=[simple_reranker_col, model_reranker_col],
                    )

                    retrieval_mode.input(
                        fn=change_retrieval_mode,
                        inputs=retrieval_mode,
                        outputs=[simple_reranker_col],
                    )

                vec_args = {
                    retrieval_mode,
                    reranker_type,
                    vector_weight,
                    keyword_weight,
                    similarity_top_k,
                    image_similarity_top_k,
                    need_image,
                    similarity_threshold,
                    reranker_model,
                }

            with gr.Column(visible=True) as llm_col:
                model_argument = gr.Accordion("Inference Parameters of LLM", open=False)
                with model_argument:
                    include_history = gr.Checkbox(
                        label="Chat history",
                        info="Query with chat history.",
                        elem_id="include_history",
                    )
                    llm_temp = gr.Slider(
                        minimum=0,
                        maximum=1,
                        step=0.001,
                        value=0.1,
                        elem_id="llm_temperature",
                        label="Temperature (choose between 0 and 1)",
                    )
                llm_args = {llm_temp, include_history}

            with gr.Column(visible=True) as search_col:
                search_model_argument = gr.Accordion(
                    "Parameters of Web Search", open=False
                )
                with search_model_argument:
                    search_api_key = gr.Text(
                        label="Bing API Key",
                        value="",
                        type="password",
                        elem_id="search_api_key",
                    )
                    search_count = gr.Slider(
                        label="Search Count",
                        minimum=5,
                        maximum=30,
                        step=1,
                        elem_id="search_count",
                    )
                    search_lang = gr.Radio(
                        label="Language",
                        choices=["zh-CN", "en-US"],
                        value="zh-CN",
                        elem_id="search_lang",
                    )
                search_args = {search_api_key, search_count, search_lang}

            with gr.Column(visible=True) as lc_col:
                prm_type = gr.Radio(
                    [
                        "Simple",
                        "General",
                        "Extract URL",
                        "Accurate Content",
                        "Custom",
                    ],
                    label="\N{rocket} Please choose the prompt template type",
                    elem_id="prm_type",
                )
                text_qa_template = gr.Textbox(
                    label="prompt template",
                    value="",
                    elem_id="text_qa_template",
                    lines=4,
                )

                def change_prompt_template(prm_type):
                    if prm_type == "Simple":
                        return {
                            text_qa_template: gr.update(
                                value=SIMPLE_PROMPTS, interactive=False
                            )
                        }
                    elif prm_type == "General":
                        return {
                            text_qa_template: gr.update(
                                value=GENERAL_PROMPTS, interactive=False
                            )
                        }
                    elif prm_type == "Extract URL":
                        return {
                            text_qa_template: gr.update(
                                value=EXTRACT_URL_PROMPTS, interactive=False
                            )
                        }
                    elif prm_type == "Accurate Content":
                        return {
                            text_qa_template: gr.update(
                                value=ACCURATE_CONTENT_PROMPTS,
                                interactive=False,
                            )
                        }
                    else:
                        return {text_qa_template: gr.update(value="", interactive=True)}

                prm_type.input(
                    fn=change_prompt_template,
                    inputs=prm_type,
                    outputs=[text_qa_template],
                )

            cur_tokens = gr.Textbox(
                label="\N{fire} Current total count of tokens", visible=False
            )

            def change_query_radio(query_type):
                if query_type == "Retrieval":
                    return {
                        vs_col: gr.update(visible=True),
                        vec_model_argument: gr.update(open=True),
                        search_model_argument: gr.update(open=False),
                        search_col: gr.update(visible=False),
                        llm_col: gr.update(visible=False),
                        model_argument: gr.update(open=False),
                        lc_col: gr.update(visible=False),
                    }
                elif query_type == "LLM":
                    return {
                        vs_col: gr.update(visible=False),
                        vec_model_argument: gr.update(open=False),
                        search_model_argument: gr.update(open=False),
                        search_col: gr.update(visible=False),
                        llm_col: gr.update(visible=True),
                        model_argument: gr.update(open=True),
                        lc_col: gr.update(visible=False),
                    }
                elif query_type == "WebSearch":
                    return {
                        vs_col: gr.update(visible=False),
                        vec_model_argument: gr.update(open=False),
                        search_model_argument: gr.update(open=True),
                        search_col: gr.update(visible=True),
                        llm_col: gr.update(visible=False),
                        model_argument: gr.update(open=False),
                        lc_col: gr.update(visible=False),
                    }
                elif query_type == "RAG (Retrieval + LLM)":
                    return {
                        vs_col: gr.update(visible=True),
                        vec_model_argument: gr.update(open=False),
                        search_model_argument: gr.update(open=False),
                        search_col: gr.update(visible=False),
                        llm_col: gr.update(visible=True),
                        model_argument: gr.update(open=False),
                        lc_col: gr.update(visible=True),
                    }

            query_type.input(
                fn=change_query_radio,
                inputs=query_type,
                outputs=[
                    vs_col,
                    vec_model_argument,
                    search_model_argument,
                    search_col,
                    llm_col,
                    model_argument,
                    lc_col,
                ],
            )

        with gr.Column(scale=8):
            css = """
            .text{
                white-space: normal !important;
                overflow:hidden;
                text-overflow:ellipsis;
                display: -webkit-box;
            }"""
            chatbot = gr.Chatbot(height=500, elem_id="chatbot", css=css)
            question = gr.Textbox(label="Enter your question.", elem_id="question")
            with gr.Row():
                submitBtn = gr.Button("Submit", variant="primary")
                clearBtn = gr.Button("Clear History", variant="secondary")

        chat_args = (
            {text_qa_template, question, query_type, chatbot, is_streaming}
            .union(vec_args)
            .union(llm_args)
            .union(search_args)
        )

        submitBtn.click(
            respond,
            chat_args,
            [chatbot],
            api_name="respond_clk",
        )
        question.submit(
            respond,
            chat_args,
            [chatbot],
            api_name="respond_q",
        )
        submitBtn.click(
            reset_textbox,
            [],
            [question],
            api_name="reset_clk",
        )
        question.submit(
            reset_textbox,
            [],
            [question],
            api_name="reset_q",
        )

        clearBtn.click(clear_history, [chatbot], [chatbot, cur_tokens])
        return {
            similarity_top_k.elem_id: similarity_top_k,
            image_similarity_top_k.elem_id: image_similarity_top_k,
            need_image.elem_id: need_image,
            retrieval_mode.elem_id: retrieval_mode,
            reranker_type.elem_id: reranker_type,
            reranker_model.elem_id: reranker_model,
            vector_weight.elem_id: vector_weight,
            keyword_weight.elem_id: keyword_weight,
            similarity_threshold.elem_id: similarity_threshold,
            prm_type.elem_id: prm_type,
            text_qa_template.elem_id: text_qa_template,
            search_lang.elem_id: search_lang,
            search_api_key.elem_id: search_api_key,
            search_count.elem_id: search_count,
        }
