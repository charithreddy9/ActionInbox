"""Evaluate the offline intent *classifier* on a small author-written synthetic holdout.
Does not evaluate deadline extraction or task usefulness; separate tests cover those.
"""
from __future__ import annotations
from collections import defaultdict
import json
from pathlib import Path
from sklearn.metrics import classification_report,confusion_matrix,accuracy_score, f1_score
from .training import HELDOUT
from .nlp import classify

ROOT=Path(__file__).resolve().parents[1]
def run():
    y_true=[label for _,label in HELDOUT]
    y_pred=[classify(text)[0] for text,_ in HELDOUT]
    labels=sorted(set(y_true))
    return dict(dataset='27 independently phrased but manually authored synthetic samples (same topics as training)',
        count=len(HELDOUT),accuracy=round(accuracy_score(y_true,y_pred),4),
        macro_f1=round(f1_score(y_true,y_pred,average="macro",zero_division=0),4),labels=labels,
        confusion_matrix=confusion_matrix(y_true,y_pred,labels=labels).tolist(),
        classification_report=classification_report(y_true,y_pred,output_dict=True,zero_division=0),
        cases=[{'text':text,'expected':expected,'predicted':pred,'passed':expected==pred} for (text,expected),pred in zip(HELDOUT,y_pred)],
        caveat='This tiny synthetic author-held-out test is a development check, not representative real-world email accuracy or date-extraction performance.')
if __name__=='__main__':
    report=run();p=ROOT/'research'/'evaluation.json';p.parent.mkdir(exist_ok=True,parents=True)
    p.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(f"Held-out: {report['accuracy']:.1%} accuracy, macro-F1={report['macro_f1']:.3f}; {report['count']} cases. Saved {p}")
