import os
from copy import deepcopy

import numpy as np
import pandas
from plantfusion.indexer import Indexer
import scipy

from openalea.lpy import *
import openalea.lpy as lpy
#import issus de simpraise
from lgrass import meteo_ephem
from lgrass import param_reproduction_functions as prf
from lgrass import cuts
from lgrass import run_caribu_lgrass
from lgrass import gen_lstring
import lgrass
import time
import pandas as pd

from plantfusion.utils import create_child_folder
from plantfusion.light_wrapper import Light_wrapper
from plantfusion.indexer import Indexer


class Simpraise_wrapper:
    """Wrapper for Simpraise model

    Constructor creates the lsysrem
    """

    def __init__(
        self,
        name="simpraise",
        indexer=Indexer(),
        in_folder="inputs",
        genet_folder="modelgenet",
        out_folder=None,
        plan_sim_file=None,
        genet_file = None,# Fichiers d'entrée
        param_plant_file = None,# un fichier de remplacement du modèle génétique qui génère une population de C et détermine le nombre de plantes du couvert        
        ongletconfigfile="exemple",
        id_scenario = 0,
        id_gener = 1,
        opt_repro = False,
        row = None,
        planter=None,
        lscene = None
    ) -> None:

        self.name = name
        self.indexer = indexer
        #self.global_index = indexer.global_order.index(name)
        #self.simpraise_index = indexer.simpraise_names.index(name)


        # read simpraise configuration files
        plan_sim = pd.read_csv(os.path.join(in_folder, plan_sim_file), sep=',')

        # Config des fichiers d'entrée
        self.INPUTS_DIRPATH = in_folder
        src = os.path.join(self.INPUTS_DIRPATH, 'insim.txt')
        dst = genet_folder
        exe = 'simpraise.exe'

        # Génération des fondateurs, première exécution du modèle génétique
        prf.rungenet(src, dst, exe, None)

        # Répertoires de lecture/écriture
        #INPUTS_DIRPATH = 'inputs'
        self.OUTPUTS_DIRPATH = 'outputs'
        GENET_DIRPATH = genet_folder

        # Charger le plan de simulation et le lsystem
        row = plan_sim.iloc[id_scenario]
        self.row = row
        name = str(row["name"])
        self.lpy_filename = os.path.join(lgrass.__path__[0], 'lgrass.lpy')
        self.lsystem = lpy.Lsystem(self.lpy_filename)
        self.lsystem.name_sim = name
        self.lstring = self.lsystem.axiom

        # Choix du fichier de lecture du C en fonction de l'option de reproduction des plantes
        self.opt_repro = row["option_reproduction"]
        if self.opt_repro != "False":
            in_genet_file = os.path.join(GENET_DIRPATH, genet_file)
        else:
            in_genet_file = None
        in_param_file = os.path.join(in_folder, param_plant_file)
        
        # Parametres des plantes
        self.lsystem.ParamP, self.lsystem.nb_plantes, self.lsystem.NBlignes, self.lsystem.NBcolonnes, self.lsystem.posPlante, self.lsystem.Plantes, self.lsystem.Genotypes, self.lsystem.flowering_model = prf.define_param(
            in_param_file=in_param_file, in_genet_file=in_genet_file, out_param_file=os.path.join(self.OUTPUTS_DIRPATH, name + '.csv'),
            id_gener=id_gener, opt_repro=self.opt_repro)


        # Parametres de simulation
        self.lsystem.option_tallage = row["option_tallage"]
        self.lsystem.option_senescence = row["option_senescence"]
        self.lsystem.option_floraison = row["option_floraison"]
        self.lsystem.option_tiller_regression = row["option_tiller_regression"]
        self.lsystem.option_morphogenetic_regulation_by_carbone = row["option_morphogenetic_regulation_by_carbone"]
        self.lsystem.derivationLength = int(row["derivationLength"])
        self.lsystem.sowing_date = row["sowing_date"]
        self.lsystem.site = row["site"]
        self.lsystem.meteo = meteo_ephem.import_meteo_data(row["meteo_path"], row['sowing_date'], row['site'])
        self.lsystem.output_induction_file_name = name + '_' + 'induction'
        self.lsystem.output_organ_lengths_file_name = name + '_' + 'organ_lengths'

        # Gestion des tontes
        opt_tontes = row["option_tontes"]
        if opt_tontes:
            self.lsystem.cutting_dates, self.lsystem.derivationLength = cuts.define_cutting_dates(self.lsystem.meteo,
                                                                                        int(row["derivationLength"]),
                                                                                        row["cutting_freq"])
        else:
            self.lsystem.cutting_dates = []

        # Initialisation des parametres de caribu
        self.dico_caribu = run_caribu_lgrass.init(path_param=in_folder, in_file='param_caribu.csv', meteo=self.lsystem.meteo, nb_plantes=self.lsystem.nb_plantes, scenario=row)
        
        # Rédaction d'un fichier de sortie
        path_out = os.path.join(self.OUTPUTS_DIRPATH, name + '_caribu.csv')
        output = open(path_out, 'w')
        output.write("GDD;Date;Day;nb_talles;biomasse_aerienne;surface_foliaire;lstring" + "\n")



    def derive(self, t):
        self.lstring = self.lsystem.derive(self.lstring, t, 1)


    def light_inputs(self, elements="triangles"):
        if elements == "triangles":
            self.lscene = self.lsystem.sceneInterpretation(self.lstring)
            return self.lscene

        else:
            print("Unknown light model")
            raise

    def light_results(self) -> None:
        return
        



    def run(self):
        
        
        self.lsystem.BiomProd, self.dico_caribu['radiation_interception'], self.dico_caribu[
            'Ray'] = run_caribu_lgrass.runcaribu(self.lstring, self.lscene, self.lsystem.current_day,
                                                    self.lsystem.tiller_appearance,
                                                    self.lsystem.nb_plantes, self.dico_caribu)
        for ID in range(self.lsystem.nb_plantes):
            self.lsystem.BiomProd[ID] = self.dico_caribu['Ray'][ID] * self.dico_caribu['RUE']  # Ray: MJ PAR ; RUE : g MJ-1
        return self.lsystem.BiomProd, self.dico_caribu['radiation_interception'], self.dico_caribu['Ray']

    def end(self):
        # Matrice de croisement des plantes
        if self.opt_repro != "False":
            mat = prf.create_seeds(self.lstring, self.lsystem.nb_plantes, self.opt_repro, self.row["cutting_freq"], self.lsystem.ParamP)
            np.savetxt(os.path.join(self.OUTPUTS_DIRPATH, self.name + "_mat.csv"), mat)
        else:
            mat = 0

        # Sauvegarder la lstring dans un répertoire pour pouvoir la charger dans une prochaine simulation
        if self.row['option_sauvegarde']:
            gen_lstring.save_lstring(self.lsystem.lstring, self.lsystem)

        # Vider le lsystem
        self.lsystem.clear()
        print(''.join((self.name, " - done")))
