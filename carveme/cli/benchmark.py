import pandas as pd
from reframed import load_cbmodel
from carveme.reconstruction.utils import load_media_db
from carveme.reconstruction.benchmark import benchmark_biolog, benchmark_essentiality, mcc
from carveme import project_dir
from subprocess import call
import argparse


organisms = {
    'bsub': 'Bacillus subtilis (168)',
    'ecol': 'Escherichia coli (K-12 MG1655)',
    'mgen': 'Mycoplasma genitalium (G-37)',
    'paer': 'Pseudomonas aeruginosa (PA01)',
    'rsol': 'Ralstonia solenacearum (GMI1000)',
    'sone': 'Shewanella oneidensis (MR-1)'
}


genomes = {
    'bsub': 'Bsubtilis_168.faa',
    'ecol': 'Ecoli_K12_MG1655.faa',
    'mgen': 'M_genitalium_G37.faa',
    'paer': 'Paeruginosa_PAO1.faa',
    'rsol': 'Rsolanacearum_GMI1000.faa',
    'sone': 'Soneidensis_MR1.faa'
}

data_path = project_dir + '/data/benchmark'

biolog_media = {
    'bsub': 'M9',
    'ecol': 'M9',
    'paer': 'M9',
    'rsol': 'M9',
    'sone': 'ShewMM'
}

essentiality_media = {
    'bsub': 'LB',
    'ecol': 'M9',
    'mgen': None,
    'paer': 'M9[succ]',
    'sone': 'LB'
}

biolog_sources = {
    'bsub': ['C', 'N', 'P', 'S'],
    'ecol': ['C', 'N', 'P', 'S'],
    'paer': ['C'],
    'rsol': ['C', 'N', 'P', 'S'],
    'sone': ['C', 'N'],
}

elements = {
    'C': 'carbon',
    'N': 'nitrogen',
    'P': 'phosphorus',
    'S': 'sulfur',
}

biolog_compounds = {
    'C': {'glc__D', 'lac__D', 'lac__L'},
    'N': {'nh4'},
    'P': {'pi'},
    'S': {'so4'},
}


def build_models():
    for org_id, genome in genomes.items():
        print(f'Carving model for {organisms[org_id]}')

        fasta_file = f"{data_path}/fasta/{genome}"
        model_file = f"{data_path}/models/{org_id}.xml"
        mediadb = f"{data_path}/media_db.tsv"

        media = set()
        if org_id in biolog_media and biolog_media[org_id]:
            media.add(biolog_media[org_id])
        if org_id in essentiality_media and essentiality_media[org_id]:
            media.add(essentiality_media[org_id])
        media = ','.join(media)

        gapfill = f'-g "{media}" --mediadb {mediadb}' if media else ''

        call(f'carve {fasta_file} -o {model_file} {gapfill} --fbc2', shell=True)


def load_models():
    models = {}
    for org_id in organisms:
        models[org_id] = load_cbmodel(f"{data_path}/models/{org_id}.xml", flavor='bigg')
    return models


def load_biolog_data():
    biolog_data = {}
    for org_id, sources in biolog_sources.items():
        biolog_data[org_id] = {}
        for source in sources:
            biolog_data[org_id][source] = \
                pd.read_csv(f'{data_path}/biolog/{org_id}/biolog_{elements[source]}.tsv', sep='\t')

    return biolog_data


def load_essentiality_data():
    essential = {}
    non_essential = {}

    for org_id in essentiality_media:
        df = pd.read_csv(f'{data_path}/essentiality/{org_id}.tsv', sep='\t')
        essential[org_id] = {'G_' + x for x in df.query('phenotype == "E"')['bigg_id']}
        non_essential[org_id] = {'G_' + x for x in df.query('phenotype == "NE"')['bigg_id']}

    return essential, non_essential


def run_biolog_benchmark(models, biolog_data, media_db):

    biolog_results = []

    for org_id, medium in biolog_media.items():
        print(f'Running biolog benchmark for {organisms[org_id]}')
        model = models[org_id]

        for source in biolog_sources[org_id]:
            compounds = set(media_db[medium]) - biolog_compounds[source]
            data = biolog_data[org_id][source]
            result = benchmark_biolog(model, compounds, data)
            result = [(org_id, source, met, res) for met, res in result.items()]
            biolog_results.extend(result)

    return pd.DataFrame(biolog_results, columns=['org', 'source', 'met', 'value'])


def run_essentiality_benchmark(models, essential, non_essential, media_db):
    essentiality_results = []

    for org_id, medium in essentiality_media.items():
        print(f'Running essentiality benchmark for {organisms[org_id]}')
        model = models[org_id]
        in_vivo = {x: True for x in essential[org_id] & set(model.genes)}
        if non_essential[org_id]:
            in_vivo.update({x: False for x in non_essential[org_id] & set(model.genes)})
        else:
            in_vivo.update({x: False for x in set(model.genes) - set(essential[org_id])})

        compounds = media_db[medium] if medium else None
        result = benchmark_essentiality(model, compounds, in_vivo)
        result = [(org_id, gene, res) for gene, res in result.items()]
        essentiality_results.extend(result)

    return pd.DataFrame(essentiality_results, columns=['org', 'gene', 'value'])


def benchmark(rebuild=True, biolog=True, essentiality=True):

    if rebuild:
        build_models()

    models = load_models()
    media_db = load_media_db(f'{data_path}/media_db.tsv')

    if biolog:
        biolog_data = load_biolog_data()
        df_biolog = run_biolog_benchmark(models, biolog_data, media_db)
        df_biolog.to_csv(f'{data_path}/results/biolog.tsv', sep='\t', index=False)
        value = mcc(df_biolog)
        print(f'Biolog final MCC value: {value:.3f}')

    if essentiality:
        essential, non_essential = load_essentiality_data()
        df_essentiality = run_essentiality_benchmark(models, essential, non_essential, media_db)
        df_essentiality.to_csv(f'{data_path}/results/essentiality.tsv', sep='\t', index=False)
        value = mcc(df_essentiality)
        print(f'Essentiality final MCC value: {value:.3f}')


def main():
    parser = argparse.ArgumentParser(description="Benchmark CarveMe using biolog and gene essentiality data")

    parser.add_argument('--skip-rebuild', action='store_true', dest='no_rebuild',
                        help="Do not rebuild models during this call.")
    parser.add_argument('--skip-biolog', action='store_true', dest='no_biolog',
                        help="Skip biolog benchmark.")
    parser.add_argument('--skip-essentiality', action='store_true', dest='no_essentiality',
                        help="Skip biolog benchmark.")

    args = parser.parse_args()

    benchmark(rebuild=(not args.no_rebuild),
              biolog=(not args.no_biolog),
              essentiality=(not args.no_essentiality))


if __name__ == '__main__':
    main()