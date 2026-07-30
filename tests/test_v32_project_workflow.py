from product_finder.workflow import create_project, list_projects, add_approval, list_approvals, save_approvals, project_metrics

def test_project_approval_roundtrip(tmp_path):
    db=tmp_path/'workflow.db'
    pid=create_project('Test Project','P-1',path=db)
    aid=add_approval(pid,'Floor drain',item_tag='FD-1',reviewer='Alex',path=db)
    df=list_approvals(pid,path=db)
    assert len(df)==1 and int(df.iloc[0]['id'])==aid
    df.loc[0,'status']='Approved'
    save_approvals(pid,df,actor='Daniel',path=db)
    metrics=project_metrics(pid,path=db)
    assert metrics['approved']==1 and metrics['completion']==100.0
    assert len(list_projects(path=db))==1
