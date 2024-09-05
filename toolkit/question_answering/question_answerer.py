# Copyright (c) 2024 Microsoft Corporation. All rights reserved.
from collections import Counter, defaultdict

import numpy as np
import scipy.spatial.distance
import tiktoken

import toolkit.question_answering.answer_builder as answer_builder
import toolkit.question_answering.answer_schema as answer_schema
import toolkit.question_answering.helper_functions as helper_functions
import toolkit.question_answering.relevance_assessor as relevance_assessor

def answer_question(
        ai_configuration,
        question,
        cid_to_text,
        cid_to_concepts,
        concept_to_cids,
        cid_to_vector,
        concept_graph,
        community_to_concepts,
        concept_to_community,
        previous_cid,
        next_cid,
        embedder,
        embedding_cache,
        answer_batch_size,
        select_logit_bias,
        adjacent_search_steps,
        relevance_test_budget,
        community_relevance_tests,
        relevance_test_batch_size,
        irrelevant_community_restart,
        chunk_progress_callback=None,
        answer_progress_callback=None,
        chunk_callback=None,
        answer_callback=None
    ):
    answer_format = answer_schema.answer_format
    answer_object = {
        "question": question,
        "title": "",
        "introduction": "",
        "content_id_sequence": [],
        "content_items": [],
        "conclusion": ""
    }
    answer_stream = []
    test_history = []
    answer_history = []
    
    all_units = []

    all_units = sorted([(cid, vector) for cid, vector in (cid_to_vector.items())], key=lambda x: x[0])


    yes_id = tiktoken.get_encoding('o200k_base').encode('Yes')[0]
    no_id = tiktoken.get_encoding('o200k_base').encode('No')[0]
    logit_bias = {yes_id: select_logit_bias, no_id: select_logit_bias}

    if chunk_progress_callback is not None:
        chunk_progress_callback(helper_functions.get_test_progress(test_history))
        
    aq_embedding = np.array(
        embedder.embed_store_one(
            question, embedding_cache
        )
    )
    relevant, seen = helper_functions.test_history_elements(test_history)
    cosine_distances = sorted(
        [
            (cid, scipy.spatial.distance.cosine(aq_embedding, vector))
            for (cid, vector) in all_units if cid not in seen
        ],
        key=lambda x: x[1],
        reverse=False,
    )

    cid_to_communities = defaultdict(set)
    community_to_cids = defaultdict(set)
    for cid, concepts in cid_to_concepts.items():
        for concept in concepts:
            if concept in concept_to_community.keys():
                community = concept_to_community[concept]
                cid_to_communities[cid].add(community)
                community_to_cids[community].add(cid)
    semantic_search_cids = [x[0] for x in cosine_distances]
    community_sequence = []
    community_to_semantic_search_cids = defaultdict(list)
    community_mean_rank = []
    for community, cids in community_to_cids.items():
        mean_rank = np.mean(sorted([semantic_search_cids.index(c) for c in cids])[:community_relevance_tests])
        community_mean_rank.append((community, mean_rank))
    community_sequence = [x[0] for x in sorted(community_mean_rank, key=lambda x: x[1])]

    for cid in semantic_search_cids:
        chunk_communities = sorted(cid_to_communities[cid], key=lambda x : len(community_to_concepts[x]), reverse=True)
        if len(chunk_communities) > 0:
            assigned_community = sorted(chunk_communities, key=lambda x: community_sequence.index(x))[0]
            community_to_semantic_search_cids[assigned_community].append(cid)

    successive_irrelevant = 0
    eliminated_communities = set()

    while len(test_history) < relevance_test_budget:
        print(f'New loop after {len(test_history)} tests')
        relevant_this_loop = False
        narrowed_community_sequence = community_sequence #[c for c in community_sequence if c not in eliminated_communities]
        for community in narrowed_community_sequence:
            relevant, seen = helper_functions.test_history_elements(test_history)
            unseen_cids = [c for c in community_to_semantic_search_cids[community] if c not in seen][:community_relevance_tests]
            if len(unseen_cids) > 0:
                is_relevant = relevance_assessor.assess_relevance(
                    ai_configuration=ai_configuration,
                    search_label=f'community {community}',
                    search_cids=unseen_cids,
                    cid_to_text=cid_to_text,
                    question=question,
                    logit_bias=logit_bias,
                    relevance_test_budget=relevance_test_budget,
                    relevance_test_batch_size=relevance_test_batch_size,
                    test_history=test_history,
                    progress_callback=chunk_progress_callback,
                    chunk_callback=chunk_callback,
                )
                relevant_this_loop |= is_relevant
                print(f'Community {community}: {is_relevant}')
                if not is_relevant:
                    eliminated_communities.add(community)
                    successive_irrelevant += 1
                    if successive_irrelevant == irrelevant_community_restart:
                        successive_irrelevant = 0
                        print(f'{successive_irrelevant} successive irrelevant communities; breaking')
                        break
                else:
                    successive_irrelevant = 0
        if not relevant_this_loop:
            print('Nothing relevant this loop')
            break

    relevant, seen = helper_functions.test_history_elements(test_history)

    # Finally, we do detail/adjacent search, which is a search of the chunks adjacent to the relevant chunks.
    adjacent_sources = list(relevant)
    adjacent_targets = set()
    for c in adjacent_sources:
        adjacent_targets.update(helper_functions.get_adjacent_chunks(c, previous_cid, next_cid, adjacent_search_steps))
    adjacent_search_cids = [x for x in adjacent_targets if x not in seen]
    print(f'Adjacent: {adjacent_search_cids}')
    relevance_assessor.assess_relevance(
        ai_configuration=ai_configuration,
        search_label='detail',
        search_cids=adjacent_search_cids,
        cid_to_text=cid_to_text,
        question=question,
        logit_bias=logit_bias,
        relevance_test_budget=relevance_test_budget,
        relevance_test_batch_size=relevance_test_batch_size,
        test_history=test_history,
        progress_callback=chunk_progress_callback,
        chunk_callback=chunk_callback,
    )
    relevant_cids, seen_cids = helper_functions.test_history_elements(test_history)
    relevant_cids.sort()
    seen_cids.sort()
    relevant_texts = [cid_to_text[cid] for cid in relevant_cids]
    answer_builder.generate_answers(
        ai_configuration=ai_configuration,
        answer_object=answer_object,
        answer_format=answer_format,
        process_chunks=relevant_texts,
        answer_batch_size=answer_batch_size,
        answer_stream=answer_stream,
        answer_callback=answer_callback,
        answer_history=answer_history,
        progress_callback=answer_progress_callback,
    )
    return (
        relevant_cids, 
        answer_stream,
        helper_functions.get_test_progress(test_history),
        helper_functions.get_answer_progress(answer_history)
    )